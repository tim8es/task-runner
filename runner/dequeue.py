"""Resolve one newly added opaque queue entry without opening private files.

This module is intentionally generic: no repository, project, payload or
processing parameters are stored in the public queue.
"""
from pathlib import Path
import os
import re
import subprocess
import sys

QUEUE_FILE = re.compile(r"queue/([0-9a-f]{32})\\.job\\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\\Z")


def job_from_commit(root, commit):
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ValueError("INVALID_QUEUE_COMMIT")
    root = Path(root)
    # A queue request must be the ONLY changed file and be newly added.
    paths = subprocess.check_output([
        "git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=root, text=True, timeout=15).splitlines()
    added = subprocess.check_output([
        "git", "diff-tree", "--no-commit-id", "--name-only", "--diff-filter=A",
        "-r", commit], cwd=root, text=True, timeout=15).splitlines()
    if len(paths) != 1 or paths != added:
        raise ValueError("INVALID_QUEUE_COMMIT_CONTENT")
    match = QUEUE_FILE.fullmatch(paths[0])
    if not match:
        raise ValueError("INVALID_QUEUE_ENTRY")
    file = root / paths[0]
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 80:
        raise ValueError("UNSAFE_QUEUE_ENTRY")
    if file.read_bytes() not in (match[1].encode(), (match[1] + "\n").encode()):
        raise ValueError("INVALID_QUEUE_JOB")
    return match[1]


def main():
    try:
        job = job_from_commit(Path.cwd(), os.environ.get("GITHUB_SHA", ""))
        output = Path(os.environ["GITHUB_OUTPUT"])
        with output.open("a", encoding="utf8") as stream:
            stream.write("job_id=" + job + "\n")
    except Exception:
        print("Queue validation failed", file=sys.stderr)
        raise SystemExit(1)
    print("Opaque queue validated")


if __name__ == "__main__":
    main()
