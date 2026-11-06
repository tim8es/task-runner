"""Public queue test with synthetic repo and opaque identifiers only."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
import io

from runner.dequeue import job_from_commit, main


class QueuedExecutorTests(unittest.TestCase):
    def setup_git(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        def git(*args):
            return subprocess.check_output(["git", "-C", str(root), *args],
                                           text=True, stderr=subprocess.DEVNULL).strip()
        git("init", "-q")
        git("config", "user.name", "Synthetic")
        git("config", "user.email", "synthetic@example.invalid")
        (root / "README.md").write_text("public fixture\n")
        git("add", "README.md")
        git("commit", "-qm", "baseline")
        return root, git

    def test_single_new_opaque_entry_is_accepted(self):
        root, git = self.setup_git()
        job = "a" * 32
        (root / "queue").mkdir()
        (root / "queue" / (job + ".job")).write_text(job + "\n")
        git("add", ".")
        git("commit", "-qm", "Generic queued execution")
        self.assertEqual(job_from_commit(root, git("rev-parse", "HEAD")), job)

    def test_extra_changed_file_is_refused(self):
        root, git = self.setup_git()
        job = "a" * 32
        (root / "queue").mkdir()
        (root / "queue" / (job + ".job")).write_text(job)
        (root / "other.txt").write_text("not allowed")
        git("add", ".")
        git("commit", "-qm", "unexpected files")
        with self.assertRaises(ValueError):
            job_from_commit(root, git("rev-parse", "HEAD"))

    def test_content_mismatch_is_refused(self):
        root, git = self.setup_git()
        job = "a" * 32
        (root / "queue").mkdir()
        (root / "queue" / (job + ".job")).write_text("b" * 32)
        git("add", ".")
        git("commit", "-qm", "mismatch")
        with self.assertRaises(ValueError):
            job_from_commit(root, git("rev-parse", "HEAD"))

    def test_edited_queue_entry_cannot_be_replayed(self):
        root, git = self.setup_git()
        job = "a" * 32
        path = root / "queue" / (job + ".job")
        path.parent.mkdir()
        path.write_text(job)
        git("add", ".")
        git("commit", "-qm", "first")
        path.write_text(job + "\n")
        git("add", ".")
        git("commit", "-qm", "replay")
        with self.assertRaises(ValueError):
            job_from_commit(root, git("rev-parse", "HEAD"))

    def test_no_private_details_in_public_log_on_failure(self):
        root, git = self.setup_git()
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"GITHUB_SHA": "invalid",
                                      "GITHUB_OUTPUT": str(root / "output")}), \
             patch("pathlib.Path.cwd", return_value=root), \
             redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit):
                main()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "Queue validation failed\n")

    def test_public_queue_has_no_specific_task_metadata(self):
        root = Path(__file__).resolve().parents[1]
        yml = (root / ".github" / "workflows" / "queued.yml").read_text()
        self.assertIn("permissions: {}", yml)
        self.assertIn("fetch-depth: 2", yml)
        self.assertIn("branches: [main]", yml)
        self.assertIn("python3 -m runner.execute", yml)
        self.assertNotIn("upload-artifact", yml)
        self.assertIn("secrets.TASK_RUNNER_ACCESS_TOKEN", yml)
        self.assertIn("steps.queued.outputs.job_id", yml)
        self.assertNotIn("repository: tim8es/", yml)


if __name__ == "__main__":
    unittest.main()
