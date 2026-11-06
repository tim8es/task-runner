# Agent instructions

## Purpose
This PUBLIC repository provides generic, free GitHub-hosted Actions execution
for TRUSTED code fetched at runtime from PRIVATE repositories. It is not a
catalogue of projects, tasks, clients, or business processes.

## Before editing
- Read `docs/UNIVERSAL_EXECUTION_V1.md` and the relevant tests.
- Treat `.github/workflows/universal.yml` and `runner/execute.py` as the
  generic v1 interface. New consumers use a private job manifest, a pinned
  private source commit, and an opaque 32-character hex `job_id`.
- Keep project-specific code, configuration, entrypoints, URLs, dependencies,
  inputs, and results in private repositories; never add them here.
- Preserve every existing workflow's name, inputs, and behavior until its
  private callers have migrated and an end-to-end run has been verified.

## Mandatory privacy and safety rules
- Never commit private repository names, source URLs, commit IDs, client names,
  internal service endpoints, secrets, transcripts, task data, or results.
- Never disclose them in workflow names, step names, dispatch inputs,
  stdout/stderr, shell tracing, error messages, artifacts, caches, summaries,
  screenshots, fixtures, test logs, or PR descriptions.
- Public runs still expose actor, timing, duration, status and generic step
  names. Do not promise secrecy for those metadata or historic public logs.
- Maintain `permissions: {}` on execution workflows and least-privilege,
  scoped credentials. Do not grant secrets to untrusted pull-request code.
- Do not log private code checkout output. Suppress private subprocess output,
  never upload private artifacts, and return task results only through a
  private destination. Never print raw exceptions from private execution.
- Private tasks are TRUSTED code, not isolated from the Actions host. Do not
  present this setup as a sandbox or a zero-knowledge processing system.

## Change workflow
1. Make minimal, backward-compatible changes in a branch/PR.
2. Test with synthetic data only; do not use real private repositories or
   secrets in public CI.
3. Run `python3 -m unittest discover -s tests -v`.
4. Validate GitHub Actions expressions (`\u0024{{ ... }}`), contract shape,
   log redaction, and compatibility with legacy entrypoints.
5. For an actual migration, verify a successful PRIVATE result and inspect
   the PUBLIC run logs before retiring the old workflow.
6. If verification or credentials are unavailable, say so explicitly rather
   than claiming successful private execution.

Detailed schema and rollout: `docs/UNIVERSAL_EXECUTION_V1.md`.
