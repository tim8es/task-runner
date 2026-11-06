# FF Qwen3 voice comparison on a public CPU runner

This repository contains **only a restricted GitHub Actions launcher**:
`.github/workflows/ff-qwen-private.yml`. Existing n8n/render workflows are
independent and unchanged.

## Trust boundary and current integration

- **Private code and encrypted jobs:** `tim8es/voice-engine`.
- **Public execution:** `tim8es/task-runner`, manual `workflow_dispatch`
  from protected `main`, with one opaque 32-hex `job_id`.
- **Private model:** `Qwen/Qwen3-TTS-12Hz-1.7B-Base`, FP32, CPU;
  no smaller model, quantization, paid API or fake fallback.
- **Private result:** GitHub Release in `tim8es/voice-engine` with
  `result.bundle` (Fernet-authenticated ciphertext containing
  `same.wav`, `new.wav`, `report.json`).
- **No personal data in public Git:** no audio, transcript, key, voice
  embeddings, prompt, unencrypted WAV, or GitHub Actions artifact.
- **Pinned worker:** exact Voice Engine commit SHA in workflow; the only
  mutable checkout is encrypted `jobs/` and `profiles/` from `voice-engine/main`.
  Do not execute code or shell scripts from staged job data.

The hosted public runner decrypts personal material temporarily during
inference. GitHub infrastructure, workflow maintainers and secret holders
are inside the trust boundary. This is **not** zero-knowledge processing.

## One-time private secret setup

Repository owner must set these two **Actions Secrets in the public
`tim8es/task-runner` repository**:

1. `VOICE_ENGINE_REPO_TOKEN`: fine-grained PAT restricted to
   **`tim8es/voice-engine` only**, with Contents read/write as required
   for private checkout and uploading the encrypted release result.
   Never scope it to all repositories.
2. `FF_JOB_FERNET_KEY`: the **legitimate retained Fernet key
   matching the encrypted `ff_owner` profile**. If one already encrypted
   the old private job and was not exposed, reuse that key. A newly generated
   key cannot decrypt the staged legacy bootstrap; rotate locally by
   decrypting with the original key and re-encrypting `reference.bundle`
   first. Never use the historically exposed `FF_VOICE_BUNDLE_KEY`.
   Do not paste any secret into workflow inputs, commits or logs.

The ChatGPT GitHub connector cannot configure Actions Secrets or trigger
`workflow_dispatch`. Without these secrets, the workflow fails before
model setup. Do not claim the model ran until actual run evidence exists.

## Reusable voice profile — no repeated audio uploads

An already encrypted legacy personal-voice job has been staged, without
decryption, at **private**
`tim8es/voice-engine/profiles/ff_owner/bootstrap.bundle`.
The private worker can reuse its embedded reference audio/transcript for
future text-only jobs **if** the configured Fernet key decrypts the
bootstrap. It prefers the smaller, separately encrypted permanent
`profiles/ff_owner/reference.bundle` when available. Migration from
legacy ciphertext, key rotation and initial owner setup are documented
in `tim8es/voice-engine/docs/OPERATIONS.md`.

For subsequent generations, prepare **only** the two new text files in
a trusted local environment. Create an encrypted job with
`python -m scripts.private_job_cli pack-texts --profile ff_owner --same
/private/same.txt --new /private/new.txt --output /private/input.bundle.b64`.
Stage **only this ciphertext** in the private Voice Engine repository at
`jobs/<job_id>/input.bundle.b64`.

Select
`Actions → FF Qwen3 1.7B - private Voice Engine job → Run workflow`
on `main`, entering **only** the opaque `job_id`.
The workflow first checks both ciphertext files and decrypts the
configured profile with a lightweight cryptography-only **preflight**.
On missing/mismatched key it fails **before** downloading Qwen weights.
On success it runs full FP32 Qwen3-TTS 1.7B on CPU and stores
`result.bundle` **only** in a private Voice Engine Release.

Recover and decrypt `same.wav`, `new.wav` and `report.json` on a
trusted local device with the same key. Verify report hashes and actually
listen to both recordings before evaluating voice likeness. Do not upload
plain WAVs to a public Actions artifact or commit personal data.

## One-time no-model profile check

First configure the two Actions Secrets, then run
`Actions → FF private voice profile preflight → Run workflow` on `main`.
This separate lightweight workflow loads **only** encrypted `profiles/`,
checks that the correct key decrypts the fixed `ff_owner` reference, and
returns a generic success/failure. It does not run Qwen or require new audio,
transcripts or text jobs. If it fails, resolve missing/mismatched Secrets or
rotate the legacy reference securely before running the full model.

## Known limitations

The archived encrypted recording must decrypt with a legitimate retained
key and contain the correct audio/transcript. If neither the original key
nor a usable recording exists, the owner must provide an audio sample once.
The two GitHub Secrets must be configured. The runner has not been certified for a full-model production run merely
because the workflow and synthetic tests pass. CPU model downloads and
inference must fit within the workflow timeout.
