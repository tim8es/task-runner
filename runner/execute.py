"""Private-source execution with a public, metadata-minimal GitHub Actions interface.

This module intentionally does not log URLs, manifests, subprocess output,
source locations, tokens, or application exceptions.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request


SCHEMA_VERSION = "task-runner/v1"
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
COMMIT_RE = re.compile(r"^[a-f0-9]{40}$")
REPO_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
REGISTRY_REF_RE = re.compile(r"^[A-Za-z0-9_./-]{1,150}$")
MAX_MANIFEST_SIZE = 65536
MAX_STEP_SECONDS = 21000
MAX_TOTAL_SECONDS = 21500
RESERVED_ENV = frozenset({
    "PATH", "HOME", "SHELL", "ENV", "BASH_ENV", "PYTHONPATH",
    "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
})


class RunnerError(Exception):
    """A private failure whose details must never enter the public log."""


def validate_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise RunnerError("Invalid job identifier")
    return job_id


def validate_repository(value: str) -> str:
    if not isinstance(value, str) or value.count("/") != 1:
        raise RunnerError("Invalid source")
    parts = value.split("/")
    if any(part in {".", ".."} or not REPO_PART_RE.fullmatch(part) for part in parts):
        raise RunnerError("Invalid source")
    return value


def validate_directory(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 250:
        raise RunnerError("Invalid working directory")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RunnerError("Invalid working directory")
    if any(ord(char) < 32 for char in value):
        raise RunnerError("Invalid working directory")
    return value


def validate_manifest(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise RunnerError("Unsupported private contract")
    if set(payload) - {"schemaVersion", "source", "execution", "environment"}:
        raise RunnerError("Unsupported private contract")
    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != {"repository", "commit"}:
        raise RunnerError("Invalid private source")
    validate_repository(source["repository"])
    if not isinstance(source["commit"], str) or not COMMIT_RE.fullmatch(source["commit"]):
        raise RunnerError("Private source must be pinned")
    execution = payload.get("execution")
    if not isinstance(execution, dict) or set(execution) != {"steps", "workingDirectory"}:
        raise RunnerError("Invalid execution")
    validate_directory(execution["workingDirectory"])
    steps = execution["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
        raise RunnerError("Invalid execution")
    total = 0
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"argv", "timeoutSeconds"}:
            raise RunnerError("Invalid execution")
        argv = step["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 64:
            raise RunnerError("Invalid execution")
        if any(
            not isinstance(arg, str) or not arg or len(arg) > 4096
            or any(ord(char) < 32 for char in arg)
            for arg in argv
        ):
            raise RunnerError("Invalid execution")
        timeout = step["timeoutSeconds"]
        if type(timeout) is not int or not 1 <= timeout <= MAX_STEP_SECONDS:
            raise RunnerError("Invalid execution")
        total += timeout
    if total > MAX_TOTAL_SECONDS:
        raise RunnerError("Execution exceeds limits")
    environment = payload.get("environment", {})
    if not isinstance(environment, dict) or len(environment) > 100:
        raise RunnerError("Invalid environment")
    for key, value in environment.items():
        if (not isinstance(key, str) or not ENV_NAME_RE.fullmatch(key)
                or key.startswith(("GITHUB_", "ACTIONS_", "RUNNER_", "TASK_RUNNER_", "GIT_"))
                or key in RESERVED_ENV or key == "TASK_JOB_ID"):
            raise RunnerError("Invalid environment")
        if not isinstance(value, dict) or len(value) != 1:
            raise RunnerError("Invalid environment")
        if "secret" in value:
            if not isinstance(value["secret"], str) or not SECRET_NAME_RE.fullmatch(value["secret"]):
                raise RunnerError("Invalid environment")
        elif value != {"jobId": True}:
            raise RunnerError("Invalid environment")
    return payload


def load_manifest(job_id: str, registry: str, ref: str, token: str) -> dict:
    validate_job_id(job_id)
    validate_repository(registry)
    if (not isinstance(ref, str) or not REGISTRY_REF_RE.fullmatch(ref)
            or ref.startswith(("/", "-")) or ".." in ref or "//" in ref):
        raise RunnerError("Invalid registry ref")
    if not token:
        raise RunnerError("Missing private access")
    url = (
        "https://api.github.com/repos/" + registry
        + "/contents/jobs/" + job_id + ".json?ref=" + ref
    )
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "universal-task-executor",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(MAX_MANIFEST_SIZE * 2 + 1)
        if len(raw) > MAX_MANIFEST_SIZE * 2:
            raise RunnerError("Invalid private contract")
        outer = json.loads(raw)
        if outer.get("encoding") != "base64":
            raise RunnerError("Invalid private contract")
        decoded = base64.b64decode(outer["content"], validate=False)
        if len(decoded) > MAX_MANIFEST_SIZE:
            raise RunnerError("Invalid private contract")
        return validate_manifest(json.loads(decoded))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise RunnerError("Private contract unavailable") from exc


def _run_silent(argv: list[str], *, cwd: Path, env: dict, timeout: int) -> None:
    # Never pass a shell string or allow child stdout/stderr into Actions logs.
    try:
        subprocess.run(
            argv, cwd=str(cwd), env=env, timeout=timeout, check=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerError("Private step failed") from exc


def checkout_private_source(repository: str, commit: str, token: str, destination: Path) -> None:
    """Fetch only a pinned commit; suppress git traces, credential prompts and output."""
    validate_repository(repository)
    if not COMMIT_RE.fullmatch(commit):
        raise RunnerError("Private source must be pinned")
    if not token:
        raise RunnerError("Missing private access")
    destination.mkdir(mode=0o700)
    askpass = destination.parent / "private-askpass.sh"
    askpass.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *Username*) printf '%s\\n' x-access-token ;;\n"
        "  *Password*) printf '%s\\n' \"$TASK_RUNNER_ACCESS_TOKEN\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    askpass.chmod(0o700)
    env = {
        **os.environ,
        "TASK_RUNNER_ACCESS_TOKEN": token,
        "GIT_ASKPASS": str(askpass),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TRACE": "0",
        "GIT_TRACE_CURL": "0",
        "GIT_CURL_VERBOSE": "0",
    }
    for key in tuple(env):
        if key.startswith("GIT_CONFIG_") and key != "GIT_CONFIG_NOSYSTEM":
            env.pop(key, None)
    try:
        _run_silent(["git", "init", "-q"], cwd=destination, env=env, timeout=60)
        _run_silent(
            ["git", "remote", "add", "origin", "https://github.com/" + repository + ".git"],
            cwd=destination, env=env, timeout=60,
        )
        _run_silent(
            ["git", "fetch", "--quiet", "--no-tags", "--depth", "1", "origin", commit],
            cwd=destination, env=env, timeout=180,
        )
        _run_silent(
            ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            cwd=destination, env=env, timeout=120,
        )
        try:
            current = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(destination), env=env, timeout=30,
                stderr=subprocess.DEVNULL,
            ).decode("ascii").strip()
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise RunnerError("Private checkout failed") from exc
        if current != commit:
            raise RunnerError("Private checkout failed")
    finally:
        askpass.unlink(missing_ok=True)


def build_worker_environment(payload: dict, secret_values: dict, job_id: str) -> dict:
    if not isinstance(secret_values, dict):
        raise RunnerError("Invalid private environment")
    worker = os.environ.copy()
    for name in list(worker):
        if (name.startswith(("TASK_RUNNER_", "GIT_", "ACTIONS_ID_TOKEN_REQUEST_"))
                or name in {"GITHUB_TOKEN", "GH_TOKEN", "GITHUB_ENV", "GITHUB_PATH",
                            "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "ACTIONS_RUNTIME_TOKEN",
                            "ACTIONS_RUNTIME_URL", "ACTIONS_CACHE_URL"}):
            worker.pop(name, None)
    worker["TASK_JOB_ID"] = job_id
    for name, binding in payload.get("environment", {}).items():
        if "jobId" in binding:
            worker[name] = job_id
        else:
            secret = secret_values.get(binding["secret"])
            if not isinstance(secret, str) or not secret:
                raise RunnerError("Private credential unavailable")
            worker[name] = secret
    return worker


def execute_job(job_id: str, registry: str, registry_ref: str, token: str, secret_values: dict) -> None:
    validate_job_id(job_id)
    plan = load_manifest(job_id, registry, registry_ref, token)
    with tempfile.TemporaryDirectory(prefix="universal-task-") as tmp:
        destination = Path(tmp) / "source"
        checkout_private_source(
            plan["source"]["repository"], plan["source"]["commit"], token, destination
        )
        workdir = (destination / plan["execution"]["workingDirectory"]).resolve()
        if not workdir.is_relative_to(destination.resolve()) or not workdir.is_dir():
            raise RunnerError("Invalid execution directory")
        worker_env = build_worker_environment(plan, secret_values, job_id)
        for step in plan["execution"]["steps"]:
            argv = [part.replace("{{job_id}}", job_id) for part in step["argv"]]
            _run_silent(argv, cwd=workdir, env=worker_env, timeout=step["timeoutSeconds"])


def main() -> int:
    try:
        job_id = validate_job_id(os.environ.get("TASK_RUNNER_JOB_ID", ""))
        registry = os.environ.get("TASK_RUNNER_REGISTRY", "")
        registry_ref = os.environ.get("TASK_RUNNER_REGISTRY_REF") or "main"
        token = os.environ.get("TASK_RUNNER_ACCESS_TOKEN", "")
        secret_values = json.loads(os.environ.get("TASK_RUNNER_ENV_JSON") or "{}")
        execute_job(job_id, registry, registry_ref, token, secret_values)
        print("Execution completed")
        return 0
    except Exception:
        # Never print the originating exception, traceback or private metadata.
        print("Execution failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
