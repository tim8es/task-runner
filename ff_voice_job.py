"""Encrypted FF voice jobs for a public compute runner and private GitHub storage.

The public runner only sees an opaque job ID in workflow inputs/logs. A single
private repository is the source/destination. Audio and text are always
Fernet-encrypted at rest, and output exists only as a private release asset.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import resource
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import zipfile
from pathlib import Path

JOB_ID = re.compile(r"[a-f0-9]{32}\Z")
INPUT_NAMES = {"reference.wav", "reference.txt", "same.txt", "new.txt"}
INPUT_FLAC_NAMES = {"reference.flac", "reference.txt", "same.txt", "new.txt"}
OUTPUT_NAMES = {"same.wav", "new.wav", "report.json"}
MAX_INPUT = 20_000_000
MAX_RESULT = 75_000_000
PRIVATE_REPO = "tim8es/test"
MODEL_SIZE = "1.7B"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"


def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("FF_JOB_FERNET_KEY", "")
    if not key:
        raise RuntimeError("FF_JOB_FERNET_KEY_NOT_CONFIGURED")
    return Fernet(key.encode("ascii"))


def _archive(files: dict[str, bytes]) -> bytes:
    with io.BytesIO() as dst:
        with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in sorted(files.items()):
                if "/" in name or "\\" in name or not name:
                    raise ValueError("UNSAFE_ARCHIVE_NAME")
                z.writestr(name, data)
        return dst.getvalue()


def _extract(ciphertext: bytes, expected: set[str], max_bytes: int) -> dict[str, bytes]:
    if len(ciphertext) > max_bytes:
        raise ValueError("PACKAGE_TOO_LARGE")
    content = _fernet().decrypt(ciphertext)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        infos = z.infolist()
        if len(infos) != len(expected) or {i.filename for i in infos} != expected:
            raise ValueError("PACKAGE_SCHEMA_INVALID")
        if sum(i.file_size for i in infos) > max_bytes:
            raise ValueError("PACKAGE_EXPANDED_TOO_LARGE")
        if any(i.is_dir() or i.file_size > max_bytes for i in infos):
            raise ValueError("PACKAGE_ENTRY_INVALID")
        return {info.filename: z.read(info.filename) for info in infos}


def make_input(reference: Path, transcript: Path, same: Path, new: Path, output: Path):
    """Encrypt inputs locally; never stage plaintext to any repository."""
    raw = reference.read_bytes()
    if reference.suffix.lower() == ".flac" and raw.startswith(b"fLaC"):
        decoded_name = "reference.flac"
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
            "stream=channels:format=duration", "-of", "json", str(reference)],
            capture_output=True, check=True, timeout=20)
        media = json.loads(probe.stdout.decode("utf8"))
        channels = int(media["streams"][0]["channels"])
        seconds = float(media["format"]["duration"])
    elif reference.suffix.lower() == ".wav" and raw.startswith(b"RIFF") and b"WAVE" in raw[:16]:
        decoded_name = "reference.wav"
        with wave.open(io.BytesIO(raw), "rb") as w:
            seconds = w.getnframes() / w.getframerate()
            channels = w.getnchannels()
    else:
        raise ValueError("REFERENCE_MUST_BE_WAV_OR_LOSSLESS_FLAC")
    if channels != 1 or not 3 <= seconds <= 30:
        raise ValueError("REFERENCE_MUST_BE_MONO_3_TO_30_S")
    entries = {
        decoded_name: raw,
        "reference.txt": transcript.read_text(encoding="utf8").strip().encode("utf8"),
        "same.txt": same.read_text(encoding="utf8").strip().encode("utf8"),
        "new.txt": new.read_text(encoding="utf8").strip().encode("utf8"),
    }
    if any(not item or len(item) > MAX_INPUT for item in entries.values()):
        raise ValueError("MISSING_OR_OVERSIZED_INPUT")
    if len(entries["reference.txt"]) > 10_000 or any(len(entries[k]) > 20_000 for k in ("same.txt", "new.txt")):
        raise ValueError("TEXT_TOO_LONG")
    sealed = _fernet().encrypt(_archive(entries))
    output.parent.mkdir(parents=True, exist_ok=True)
    # Fernet ciphertext is already authenticated, URL-safe Base64 ASCII.
    output.write_text(sealed.decode("ascii") + "\n", encoding="ascii")
    return len(sealed)


def _private_api(path: str, token: str, data: bytes | None = None,
                 method: str | None = None, content_type: str = "application/json"):
    url = "https://api.github.com/repos/" + PRIVATE_REPO + path
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if data is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=35) as response:
        payload = response.read(250_000)
        return json.loads(payload.decode("utf8")) if payload else {}


def _upload_private_release(token: str, job_id: str, encrypted: bytes):
    """Only a private release; no public Actions artifact, git commit or stdout."""
    if not token:
        raise RuntimeError("FF_PRIVATE_REPO_TOKEN_NOT_CONFIGURED")
    tag = "ff-voice-" + job_id
    try:
        release = _private_api("/releases/tags/" + tag, token)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        body = json.dumps({"tag_name": tag, "target_commitish": "main",
                           "name": tag, "draft": False, "prerelease": True,
                           "generate_release_notes": False,
                           "body": "Private encrypted FF voice comparison (no plaintext)."}).encode()
        release = _private_api("/releases", token, data=body, method="POST")
    else:
        for asset in release.get("assets", []):
            if asset.get("name") == "result.bundle" and asset.get("state") == "uploaded":
                raise RuntimeError("JOB_ALREADY_HAS_PRIVATE_RESULT")
            if asset.get("name") == "result.bundle" and asset.get("state") != "uploaded":
                _private_api("/releases/assets/" + str(int(asset["id"])), token,
                             method="DELETE")
    upload = urllib.parse.urlparse(release["upload_url"].split("{", 1)[0])
    if upload.scheme != "https" or upload.hostname != "uploads.github.com":
        raise RuntimeError("UNTRUSTED_RELEASE_UPLOAD_URL")
    endpoint = release["upload_url"].split("{", 1)[0] + "?name=result.bundle"
    request = urllib.request.Request(endpoint, data=encrypted, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/octet-stream",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != 201:
            raise RuntimeError("PRIVATE_RELEASE_UPLOAD_FAILED")
        asset = json.loads(response.read(50000).decode("utf8"))
    if asset.get("name") != "result.bundle" or asset.get("size") != len(encrypted):
        raise RuntimeError("PRIVATE_RESULT_RECEIPT_INVALID")


def run(job_id: str, private_root: Path):
    """Only sanitized status goes to public logs; no personal text/audio."""
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("INVALID_JOB_ID")
    token = os.environ.get("FF_PRIVATE_REPO_TOKEN", "")
    if not token:
        raise RuntimeError("FF_PRIVATE_REPO_TOKEN_NOT_CONFIGURED")
    filename = private_root / "jobs" / job_id / "input.bundle.b64"
    if not filename.is_file() or filename.is_symlink() or filename.stat().st_size > MAX_INPUT * 1.4:
        raise ValueError("PRIVATE_JOB_MISSING_OR_INVALID")
    encrypted_input = b"".join(filename.read_bytes().split())
    # Decode is performed only after decryption, inside the ephemeral runner.
    content = _fernet().decrypt(encrypted_input)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = set(z.namelist())
    if names not in (INPUT_NAMES, INPUT_FLAC_NAMES):
        raise ValueError("PRIVATE_INPUT_SCHEMA_INVALID")
    package = _extract(encrypted_input, names, MAX_INPUT)
    import numpy as np
    import soundfile as sf
    from scripts.tts_qwen import Qwen3VoiceCloner

    results = {}
    report = {"model": MODEL_ID, "model_size": MODEL_SIZE,
              "engine": "qwen3_clone", "dtype": "float32", "device": "cpu",
              "source": "encrypted_private_job", "clips": {}}
    with tempfile.TemporaryDirectory(prefix="ff-private-voice-") as temp:
        root = Path(temp)
        ref = root / "reference.wav"
        if "reference.flac" in package:
            flac = root / "reference.flac"
            flac.write_bytes(package["reference.flac"])
            with open(os.devnull, "w") as devnull:
                subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-y",
                    "-i", str(flac), "-ar", "24000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(ref)],
                    stdout=devnull, stderr=devnull, check=True, timeout=30)
            flac.unlink()
        else:
            ref.write_bytes(package["reference.wav"])
        ref_text = package["reference.txt"].decode("utf8")
        started = time.perf_counter()
        # Do not let upstream model/framework write any private prompt into logs.
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                cloner = Qwen3VoiceCloner(ref, ref_text, model_size=MODEL_SIZE)
                for label in ("same", "new"):
                    story = package[label + ".txt"].decode("utf8")
                    audio, rate, model = cloner.synthesize(story, language="ru")
                    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                    if model != MODEL_ID or not 24000 <= rate <= 48000:
                        raise RuntimeError("MODEL_OR_SAMPLE_RATE_UNEXPECTED")
                    duration = len(audio) / rate
                    if not 1.0 <= duration <= 180 or not np.isfinite(audio).all():
                        raise RuntimeError("VOICE_OUTPUT_INVALID")
                    if np.max(np.abs(audio)) > 1.0 or np.sqrt(np.mean(audio ** 2)) < 0.002:
                        raise RuntimeError("VOICE_LEVEL_INVALID")
                    result_file = root / (label + ".wav")
                    sf.write(result_file, audio, rate, subtype="PCM_16")
                    wav = result_file.read_bytes()
                    results[label + ".wav"] = wav
                    report["clips"][label] = {"seconds": round(duration, 3),
                        "rate": int(rate),
                        "text_sha256": hashlib.sha256(package[label + ".txt"]).hexdigest(),
                        "audio_sha256": hashlib.sha256(wav).hexdigest()}
        report["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        report["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        results["report.json"] = json.dumps(report, ensure_ascii=False).encode("utf8")
        sealed = _fernet().encrypt(_archive(results))
        if len(sealed) > MAX_RESULT:
            raise RuntimeError("ENCRYPTED_RESULT_TOO_LARGE")
        _upload_private_release(token, job_id, sealed)
    print("FF_PRIVATE_QWEN_COMPLETE")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    pack = sub.add_parser("pack")
    pack.add_argument("--reference", type=Path, required=True)
    pack.add_argument("--transcript", type=Path, required=True)
    pack.add_argument("--same", type=Path, required=True)
    pack.add_argument("--new", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    exe = sub.add_parser("run")
    exe.add_argument("--job-id", required=True)
    exe.add_argument("--private-root", type=Path, required=True)
    un = sub.add_parser("unpack")
    un.add_argument("--input", type=Path, required=True)
    un.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.action == "pack":
        make_input(args.reference, args.transcript, args.same, args.new, args.output)
        print("ENCRYPTED_FF_JOB_CREATED")
    elif args.action == "run":
        try:
            run(args.job_id, args.private_root)
        except Exception:
            # Public logs MUST NOT contain private exception messages, tracebacks,
            # audio, transcripts, API paths, or model output.
            print("FF_PRIVATE_QWEN_FAILED", file=sys.stderr)
            sys.exit(1)
    else:
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        files = _extract(args.input.read_bytes(), OUTPUT_NAMES, MAX_RESULT)
        for name, value in files.items():
            (output / name).write_bytes(value)
        print("PRIVATE_VOICE_RESULT_DECRYPTED")


if __name__ == "__main__":
    main()