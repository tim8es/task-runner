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
  mutable checkout is encrypted `jobs/` from `voice-engine/main`.
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
2. `FF_JOB_FERNET_KEY`: new random Fernet key, also held on the trusted
   local machine that creates/decrypts jobs. Do not use the historically
   exposed `FF_VOICE_BUNDLE_KEY` and do not paste any secret into workflow
   inputs, commits, or logs.

The ChatGPT GitHub connector cannot configure Actions Secrets or trigger
`workflow_dispatch`. Without these secrets, the workflow fails before
model setup. Do not claim the model ran until actual run evidence exists.

## Generate the same-text / new-text comparison

Use the instructions in `tim8es/voice-engine/docs/OPERATIONS.md`.
The local job preparation and decryption entry point is
`python -m scripts.private_job_cli` in the **private** Voice Engine repo.

Prepare an authorized speaker reference from the actual recording using
`python -m scripts.audio_improve` with
`--preset conservative --strength 0.55` (moderate, not strong) and a
word-for-word transcript of the selected sample. Put the verbatim original
comparison story in `same.txt` and a different story of comparable
length/style in `new.txt`. Do not include emotion-direction labels in
the spoken text.

Encrypted input is staged only as
`voice-engine/jobs/<job_id>/input.bundle.b64`. Choose
`Actions → FF Qwen3 1.7B - private Voice Engine job → Run workflow`
on `main`, entering the opaque `job_id` only.

After success, use the authenticated GitHub CLI to retrieve the private
`ff-voice-<job_id>` release from `tim8es/voice-engine`, then decrypt
`result.bundle` **locally** using the same Fernet key. Listen to both WAVs,
verify their hashes against `report.json`, and compare voice similarity.

Do not store decrypted samples in public releases or commit them to public
repositories. Dispose of private source and result material under the
agreed retention policy.

## Known limitations

The original user recording must be locally available, the selected
reference transcript must match it, and the two GitHub secrets must be set.
The runner has not been certified for a full-model production run merely
because the workflow and synthetic tests pass. CPU model downloads and
inference must fit within the workflow timeout.
