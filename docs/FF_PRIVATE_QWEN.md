# FF: full Qwen3 1.7B on PUBLIC compute, PRIVATE voice and results

The existing `render-short.yml` integration is left unchanged. New entrypoint:
`task-runner/.github/workflows/ff-qwen-private.yml`.

**Trust boundaries:** The public Actions UI sees only a random 32-character
hexadecimal `job_id` and static status. Encrypted input lives solely in private
`tim8es/test` (`jobs/<job_id>/input.bundle.b64`). The private result is one
**encrypted** `result.bundle` attached to a GitHub Release in `tim8es/test`.
No plaintext voice, prompt, transcript, WAV, or result is committed to
`task-runner`, printed, or uploaded to its public Actions artifacts.

**Important qualification:** During inference the GitHub-hosted public runner
must temporarily decrypt the recording in its private process memory/disk.
GitHub infrastructure and anyone who can modify a trusted workflow or control
its secrets are in the trust boundary. This is not zero-knowledge processing.
Use a protected `main` branch, restrict Actions editors and secret access,
rotate credentials after any suspected compromise and review workflow changes.
A private repository/release becoming public will reveal stored ciphertext;
keep the Fernet key separate and private.

## One-time setup (repository owner)

1. Create a **fine-grained GitHub PAT** restricted to **`tim8es/test` only**, with
   repository **Contents: Read and write**. Add the PAT as Actions repository
   secret `FF_PRIVATE_REPO_TOKEN` in public **`tim8es/task-runner`**. It is used
   only by the isolated FF workflow (checkout private data and upload private
   release). It is **not** reused by n8n.
2. Generate a fresh Fernet secret locally and store it as another Actions secret
   in `tim8es/task-runner`: `FF_JOB_FERNET_KEY`.
   **Never use the previously exposed `FF_VOICE_BUNDLE_KEY`.**
   Do not commit the key, paste it in dispatch input or upload it to a repository.
3. The same key must be available on the **trusted local device/chat workspace**
   for creating/decrypting job bundles. Never add secrets to logs or shell history.

## Prepare one private job

Use the **original lossless 24-second reference**, the word-for-word transcript
of that selected reference, and two separate story files. The prepared moderate
noise-reduced reference in this experiment is converted to **lossless FLAC** to
keep the private Git text package smaller; FFmpeg restores it to WAV before Qwen.

```bash
export FF_JOB_FERNET_KEY="$(cat /private/FF_JOB_FERNET_KEY.txt)"
python ff_voice_job.py pack \
  --reference /private/reference.flac \
  --transcript /private/reference.txt \
  --same /private/same.txt --new /private/new.txt \
  --output /private/input.bundle.b64
unset FF_JOB_FERNET_KEY
```

Commit **only the Fernet ciphertext** to private repository path
`jobs/<32-character random ID>/input.bundle.b64` (UTF-8 ASCII).
Never commit plaintext voice, text or key, even to the private repo.

In `tim8es/task-runner → Actions → FF Qwen3 1.7B - private job on public CPU → Run workflow`, select the **main** branch and enter **only the opaque job ID**.
No payload, key or personal words go into workflow inputs.

The workflow checks out only private `jobs/`, checks out the **pinned** public FF
Qwen adapter, then loads **`Qwen/Qwen3-TTS-12Hz-1.7B-Base`** with `float32` on
CPU. It creates two **Russian** samples using the same cloned voice prompt.
GPU, quantization, smaller model, external paid TTS and unrelated fallbacks are
not used. Expect weight download and CPU inference on each cold runner.

## Recover outputs privately

Use a GitHub-authenticated local CLI session with access to `tim8es/test`:

```bash
export JOB_ID='<your-job-id>'
gh release download "ff-voice-${JOB_ID}" \
  -R tim8es/test -p result.bundle -D /private/results
export FF_JOB_FERNET_KEY="$(cat /private/FF_JOB_FERNET_KEY.txt)"
python ff_voice_job.py unpack \
  --input /private/results/result.bundle --output-dir /private/results/clear
unset FF_JOB_FERNET_KEY
```

Expected output: `same.wav`, `new.wav`, `report.json`. Inspect the audio,
compare the user's real recording to the model-generated *same text*, and judge
generalization on *new text*. Don't assume that repeating a text proves voice
similarity or that an encrypted successful job passes subjective QA.

After retrieval, delete private release and encrypted job when no longer needed.
The deleted Git blobs may still exist in history temporarily, but remain
ciphertext protected by the separate key.

## Operational limitations

- A GitHub connector **cannot create repository Secrets** in this chat. Two
  one-time settings above require the repository owner. Until set, the private
  model run fails early without downloading Qwen or exposing personal material.
- Public workflow has `permissions: {}` and **no** `upload-artifact`, printing,
  private HTTP callback, or n8n integration. n8n task-runner jobs remain intact.
- Current FF adapter has a **project-side 3–30 second validation**, not a
  documented universal Qwen maximum. We use the selected 23.75-second sample.
- Private release persists until manually removed. No automated public upload.