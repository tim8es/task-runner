"""Public task-runner runs pinned private Voice Engine code with opaque IDs only."""
import re
import unittest
from pathlib import Path


class PrivateVoiceRunnerContract(unittest.TestCase):
    def test_public_workflow_is_private_data_free_and_pinned(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ff-qwen-private.yml").read_text()
        self.assertIn("permissions: {}", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("repository: tim8es/voice-engine", workflow)
        self.assertIn("ref: e75ba8375f11562b331f77855c8d536c7bed94cc", workflow)
        self.assertIn("ref: main", workflow)  # encrypted jobs, never executed
        self.assertIn("python -m scripts.private_worker", workflow)
        self.assertIn("private_data/jobs/", workflow)
        self.assertIn("profiles", workflow)
        self.assertIn("python -m scripts.private_worker --preflight", workflow)
        self.assertIn("no model download attempted", workflow)
        self.assertIn("torch==2.8.0", workflow)
        self.assertIn("FF_JOB_FERNET_KEY", workflow)
        self.assertIn("VOICE_ENGINE_REPO_TOKEN", workflow)
        self.assertIn("FF_VOICE_ENGINE_TOKEN", workflow)
        self.assertIn(">/dev/null 2>&1", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("tim8es/test", workflow)
        self.assertNotIn("FF_PRIVATE_REPO_TOKEN", workflow)
        self.assertNotIn("0.6B", workflow)
        self.assertFalse((root / "ff_voice_job.py").exists())
        self.assertFalse((root / "jobs").exists())

    def test_one_time_voice_profile_check_is_private_and_model_free(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" /
                    "ff-voice-profile-preflight.yml").read_text()
        self.assertIn("permissions: {}", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("repository: tim8es/voice-engine", workflow)
        self.assertIn("ref: e75ba8375f11562b331f77855c8d536c7bed94cc", workflow)
        self.assertIn("VOICE_ENGINE_REPO_TOKEN", workflow)
        self.assertIn("FF_JOB_FERNET_KEY", workflow)
        self.assertIn("python -m scripts.private_worker --check-profile", workflow)
        self.assertIn("profiles", workflow)
        self.assertIn(">/dev/null 2>&1", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("tim8es/test", workflow)
        self.assertNotIn("qwen-tts", workflow)
        self.assertNotIn("torch==", workflow)

    def test_dispatch_accepts_only_an_opaque_id(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ff-qwen-private.yml").read_text()
        block = workflow.split("workflow_dispatch:", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(len(re.findall(r"^      [a-z_]+:$", block, re.M)), 1)
        self.assertIn("job_id:", block)
        self.assertIn("^[a-f0-9]{32}$", workflow)


if __name__ == "__main__":
    unittest.main()
