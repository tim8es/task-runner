"""Public-runner regression tests use only synthetic, non-personal audio."""
import base64
import io
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from ff_voice_job import INPUT_NAMES, OUTPUT_NAMES, _archive, _extract, make_input, JOB_ID, MODEL_ID


class TestFFPrivateVoiceQueue(unittest.TestCase):
    def test_job_id_is_strictly_opaque(self):
        self.assertTrue(JOB_ID.fullmatch("a" * 32))
        for value in ["my-voice", "../test", "a" * 31, "a" * 33, "a" * 32 + "/secret", "hi world"]:
            self.assertFalse(JOB_ID.fullmatch(value), value)

    def test_private_bundle_roundtrip_and_mismatch_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "reference.wav"
            with wave.open(str(ref), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\x00\x00" * (24000 * 5))
            for label, text in [("reference", "Synthetic speech, not a real speaker"),
                                ("same", "Synthetic same sample."),
                                ("new", "Synthetic new text!")]:
                (root / (label + ".txt")).write_text(text, encoding="utf8")
            key = Fernet.generate_key().decode()
            bundle = root / "input.bundle.b64"
            with patch.dict(os.environ, {"FF_JOB_FERNET_KEY": key}):
                make_input(ref, root / "reference.txt", root / "same.txt", root / "new.txt", bundle)
                data = bundle.read_bytes().strip()
                self.assertNotIn(b"Synthetic", data)
                files = _extract(data, INPUT_NAMES, 20_000_000)
                self.assertEqual(files["new.txt"], b"Synthetic new text!")
                output = _archive({"same.wav": b"RIFF1234WAVE", "new.wav": b"RIFF1234WAVE",
                                   "report.json": json.dumps({"model": MODEL_ID}).encode()})
                decoded = _extract(Fernet(key).encrypt(output), OUTPUT_NAMES, 75_000_000)
                self.assertIn(b'1.7B-Base', decoded["report.json"])
            with patch.dict(os.environ, {"FF_JOB_FERNET_KEY": Fernet.generate_key().decode()}):
                with self.assertRaises(Exception):
                    _extract(data, INPUT_NAMES, 20_000_000)

    def test_public_workflow_has_no_public_artifacts_or_personal_inputs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ff-qwen-private.yml")
        if not workflow.exists():
            workflow = root / "ff-qwen-private.yml"  # local authoring layout
        text = workflow.read_text(encoding="utf8")
        self.assertIn("permissions: {}", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("tim8es/test", text)
        self.assertIn("FF_PRIVATE_REPO_TOKEN", text)
        self.assertIn("FF_JOB_FERNET_KEY", text)
        self.assertIn("torch==2.8.0", text)
        self.assertNotIn("upload-artifact", text)
        self.assertNotIn("0.6B", text)

    def test_zip_slip_and_missing_files_fail(self):
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"FF_JOB_FERNET_KEY": key}):
            for bad in [{"../../password.txt": b"x"}, {"same.wav": b"x"}]:
                with self.assertRaises(ValueError):
                    encrypted = Fernet(key).encrypt(_archive(bad))
                    _extract(encrypted, OUTPUT_NAMES, 75_000_000)


if __name__ == "__main__":
    unittest.main()