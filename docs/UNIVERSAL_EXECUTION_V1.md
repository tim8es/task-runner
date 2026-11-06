# Universal execution contract (v1)

This public repository is an execution host, not a project or task catalogue.
The new workflow .github/workflows/universal.yml accepts only a randomly
generated 32-character lowercase hexadecimal job ID (128 bits). All
project-specific routing and code lives in private repositories. Existing
workflows remain available, with their original interfaces unchanged.

## Privacy and trust boundary

Publicly observable: action run timestamps, duration, actor, status, generic
workflow/job/step names, and total number of runs. The public checkout and
generic executor are visible as well.

Private by design: the registry repository, source repository, pinned private
commit, entrypoint, dependencies, task parameters, callback endpoints, private
credentials, results, and application errors. Private commands send stdout and
stderr to DEVNULL; no Actions artifact or job summary is created.

The job ID is not confidential, but must be unpredictable (for example,
Python secrets.token_hex(16)). Never put plaintext task data into dispatch inputs.

Caveats:
- GitHub and runner administrators are inside the trust boundary.
- Trusted private code executes on the hosted machine. This is NOT a sandbox
  isolating malicious tasks from one another or from the host; private code
  can access the network and potentially inspect parent-process resources.
- A workflow must not execute untrusted pull-request code with secrets.
- Suppressing application output reduces accidental disclosure, but a malicious
  worker, compromised dependency, or misconfigured private callback can leak.
- Already-published legacy workflow names, endpoints, logs, and Git history
  are not erased by this change. Treat previously disclosed metadata as public.

## Required GitHub Actions secrets in the PUBLIC runner

TASK_RUNNER_REGISTRY: private registry repository slug (owner/repo).
TASK_RUNNER_ACCESS_TOKEN: token scoped to Contents:read on the registry and
                          on the private source repositories required by jobs.
TASK_RUNNER_REGISTRY_REF: optional private registry ref, default main.
TASK_RUNNER_ENV_JSON: optional JSON object mapping references to secret
                      values, e.g. {"example_key":"secret-value"}.

Protect the public default branch and the private registry from untrusted
changes. Prefer short-lived, narrowly scoped credentials where feasible.
For unrelated trust domains, split runner credentials or runner deployments.

## Private manifest contract

Before dispatching a job, create a manifest at
jobs/<job_id>.json on the private registry branch. For example:

~~~json
{
  "schemaVersion": "task-runner/v1",
  "source": {
    "repository": "example/private-source",
    "commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "execution": {
    "workingDirectory": ".",
    "steps": [
      {
        "argv": ["python3", "-m", "pip", "install", "-r", "requirements.txt"],
        "timeoutSeconds": 600
      },
      {
        "argv": ["python3", "-m", "private_worker", "--id", "{{job_id}}"],
        "timeoutSeconds": 1800
      }
    ]
  },
  "environment": {
    "PRIVATE_SERVICE_TOKEN": {"secret": "example_key"},
    "REQUEST_ID": {"jobId": true}
  }
}
~~~

All example names above are placeholders, not concrete private project data.
Every private source must reference a FULL 40-character commit SHA, not a
branch or tag. Commands are argv arrays, never interpolated shell strings.
The exact placeholder {{job_id}} may appear in a command argument.
A relative workingDirectory must resolve inside the checked-out source.
Each step has a timeout; up to 16 are accepted, and the sum must fit within
the public runner's job duration.

Do not place secret values in the manifest itself. Environment bindings
must refer to keys in TASK_RUNNER_ENV_JSON or to the opaque ID. The
TASK_JOB_ID variable is injected automatically. GitHub Actions output-related
environment variables and the bootstrap token are not intentionally passed
to the child task. Private code handles its own secure results transfer
back to a private destination. No public artifact upload is supported.

To trigger the generic workflow through GitHub REST, POST to
/repos/<public-owner>/<public-repo>/actions/workflows/universal.yml/dispatches
using an Actions:write dispatch token and an input containing ONLY the ID:

~~~json
{"ref":"main","inputs":{"job_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}
~~~

The manifest must exist in the private registry before dispatch.
Do not put a private repo slug, client identifier, callback address, secret,
or plaintext task input into the public dispatch event.

## Gradual migration and compatibility

Existing workflow filenames, workflow_dispatch input signatures, secrets,
private SHA pins, callback integrations and users remain unchanged.
The universal runner is additive. A trusted private consumer must be
migrated, tested end-to-end against a PRIVATE result, and its public logs
inspected before retiring its legacy workflow. Only remove a legacy
workflow once all clients have migrated. Historic public logs and Git
history may still reveal old identifiers after the legacy file is removed.

The synthetic public contract test does not access private credentials or
prove an end-to-end private run.

## Optional zero-API dispatch through an opaque public queue

For environments where trusted tooling can commit but cannot call the workflow
API, `queued.yml` provides an additive generic trigger. Stage the private
`jobs/<job_id>.json` manifest **first**. Then, as a trusted committer on public
`main`, create one new file `queue/<job_id>.job` with content exactly
`<job_id>` followed by an optional newline. Use a single-file commit; any
additional changed file, edited existing entry, invalid ID, or unexpected
content is rejected. The workflow starts after the push and calls the same
universal `runner.execute`. No public artifact or private details are emitted.

Public observers can see this opaque ID, the committer, timestamps, execution
duration, state and repository history. This is not anonymous execution and
GitHub/Actions operators have access to the runner environment. The queue is
not a permission boundary: public branch write access must remain restricted.
Do not use public pull requests to trigger access to private credentials.

Use a new random job ID for each run, even when benchmarking the same private
input. The private registry manifest stays pinned to an immutable reviewed
source commit. The manual `universal.yml` interface and all legacy workflows
remain unchanged. Avoid storing tasks or their parameters in public file
contents, commit messages, or branch names.
