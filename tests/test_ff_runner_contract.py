"""Public task-runner must dispatch only opaque data to pinned private FF code."""
import unittest
from pathlib import Path


class PrivateFFRunnerContract(unittest.TestCase):
    def test_public_actions_remains_data_free(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ff-qwen-private.yml").read_text()
        self.assertIn("permissions: {}", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("ref: 6784d7c9379f7c020d348adfc264f320db124236", workflow)
        self.assertIn("private_code/scripts/ff_voice_job.py", workflow)
        self.assertIn("private_data/jobs/", workflow)
        self.assertIn("torch==2.8.0", workflow)
        self.assertIn("FF_JOB_FERNET_KEY", workflow)
        self.assertIn("FF_PRIVATE_REPO_TOKEN", workflow)
        self.assertIn(">/dev/null 2>&1", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("0.6B", workflow)
        self.assertFalse((root / "ff_voice_job.py").exists())
        self.assertFalse((root / "jobs").exists())


if __name__ == "__main__":
    unittest.main()
