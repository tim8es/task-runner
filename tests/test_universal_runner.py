"""Synthetic tests: no real private repository, network access or credentials needed."""

import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from runner import execute as runner


JOB_ID = "a" * 32
COMMIT = "b" * 40


def private_manifest():
    return {
        "schemaVersion": "task-runner/v1",
        "source": {"repository": "example/private-source", "commit": COMMIT},
        "execution": {
            "workingDirectory": ".",
            "steps": [
                {"argv": ["python3", "-m", "private_task", "--id", "{{job_id}}"],
                 "timeoutSeconds": 120},
            ],
        },
        "environment": {
            "PRIVATE_TOKEN": {"secret": "private_token"},
            "PROCESS_ID": {"jobId": True},
        },
    }


class RunnerContractTests(unittest.TestCase):
    def test_only_opaque_random_looking_identifier_is_accepted(self):
        self.assertEqual(runner.validate_job_id(JOB_ID), JOB_ID)
        for value in ["", "shorts-123", "z" * 32, "A" * 32, "../private", JOB_ID + "\n"]:
            with self.subTest(value=value), self.assertRaises(runner.RunnerError):
                runner.validate_job_id(value)

    def test_private_manifest_valid(self):
        self.assertEqual(runner.validate_manifest(private_manifest()), private_manifest())

    def test_reject_unpinned_or_unsafe_source(self):
        for value in ["main", "123", "c" * 39, "z" * 40]:
            payload = private_manifest()
            payload["source"]["commit"] = value
            with self.assertRaises(runner.RunnerError):
                runner.validate_manifest(payload)
        for value in ["../repo", "example/../repo", "example/repo/extra",
                      "https://example.org/repo", "example/.."]:
            payload = private_manifest()
            payload["source"]["repository"] = value
            with self.assertRaises(runner.RunnerError):
                runner.validate_manifest(payload)

    def test_reject_path_traversal_and_unbounded_execution(self):
        for path in ["../private", "/tmp", r"..\private", "foo/../../secret"]:
            payload = private_manifest()
            payload["execution"]["workingDirectory"] = path
            with self.assertRaises(runner.RunnerError):
                runner.validate_manifest(payload)
        payload = private_manifest()
        payload["execution"]["steps"][0]["timeoutSeconds"] = 25000
        with self.assertRaises(runner.RunnerError):
            runner.validate_manifest(payload)

    def test_reject_environment_override_and_literal_credentials(self):
        for name in ["GITHUB_OUTPUT", "ACTIONS_RUNTIME_TOKEN", "PATH", "GIT_TRACE",
                     "TASK_RUNNER_ACCESS_TOKEN", "TASK_JOB_ID"]:
            payload = private_manifest()
            payload["environment"] = {name: {"secret": "key"}}
            with self.assertRaises(runner.RunnerError):
                runner.validate_manifest(payload)
        payload = private_manifest()
        payload["environment"] = {"MY_TOKEN": {"value": "plaintext-secret"}}
        with self.assertRaises(runner.RunnerError):
            runner.validate_manifest(payload)

    def test_worker_only_receives_allowlisted_credentials(self):
        with mock.patch.dict(os.environ, {
            "TASK_RUNNER_ACCESS_TOKEN": "bootstrap-password",
            "TASK_RUNNER_ENV_JSON": "credential-map",
            "GITHUB_OUTPUT": "/tmp/output",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc",
            "GH_TOKEN": "github-token",
        }):
            env = runner.build_worker_environment(
                private_manifest(), {"private_token": "only-this-secret"}, JOB_ID
            )
        self.assertEqual(env["PRIVATE_TOKEN"], "only-this-secret")
        self.assertEqual(env["PROCESS_ID"], JOB_ID)
        self.assertEqual(env["TASK_JOB_ID"], JOB_ID)
        for name in ["TASK_RUNNER_ACCESS_TOKEN", "TASK_RUNNER_ENV_JSON",
                     "GITHUB_OUTPUT", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "GH_TOKEN"]:
            self.assertNotIn(name, env)

    def test_private_manifest_download_uses_credentials_without_logging(self):
        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit=-1):
                content = base64.b64encode(json.dumps(private_manifest()).encode()).decode()
                return json.dumps({"encoding": "base64", "content": content}).encode()

        with mock.patch.object(runner.urllib.request, "urlopen", return_value=DummyResponse()) as open_mock:
            result = runner.load_manifest(JOB_ID, "example/private-registry", "main", "token")
        self.assertEqual(result["schemaVersion"], "task-runner/v1")
        request = open_mock.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertIn("jobs/" + JOB_ID + ".json", request.full_url)

    def test_subprocess_output_and_error_are_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
                runner._run_silent(
                    [sys.executable, "-c",
                     "import sys; print('sensitive stdout'); print('sensitive stderr', file=sys.stderr)"],
                    cwd=Path(tmp), env=os.environ.copy(), timeout=10,
                )
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(errors.getvalue(), "")

    def test_real_private_code_path_cannot_escape_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            external = Path(tmp) / "outside"
            external.mkdir()
            plan = private_manifest()
            plan["execution"]["workingDirectory"] = "redirect"

            def fake_checkout(_repository, _commit, _token, destination):
                destination.mkdir()
                (destination / "redirect").symlink_to(external, target_is_directory=True)

            with (mock.patch.object(runner, "load_manifest", return_value=plan),
                  mock.patch.object(runner, "checkout_private_source", side_effect=fake_checkout)):
                with self.assertRaises(runner.RunnerError):
                    runner.execute_job(JOB_ID, "example/registry", "main", "token", {})

    def test_private_exception_is_redacted_from_public_error(self):
        with mock.patch.dict(os.environ, {"TASK_RUNNER_JOB_ID": JOB_ID}):
            out, err = io.StringIO(), io.StringIO()
            with (mock.patch.object(runner, "execute_job",
                                    side_effect=RuntimeError("repo-name-and-secret")),
                  redirect_stdout(out), redirect_stderr(err)):
                status = runner.main()
        self.assertEqual(status, 1)
        self.assertNotIn("repo-name-and-secret", err.getvalue())
        self.assertEqual(err.getvalue(), "Execution failed\n")

    def test_failure_reports_no_private_diagnostics(self):
        with mock.patch.dict(os.environ, {"TASK_RUNNER_JOB_ID": "private-name"}):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                status = runner.main()
        self.assertEqual(status, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "Execution failed\n")

    def test_entrypoint_has_no_embedded_project_metadata(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".github/workflows/universal.yml").read_text()
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("permissions: {}", text)
        self.assertIn("run: python3 -m runner.execute", text)
        self.assertNotIn("upload-artifact", text)
        self.assertNotIn("repository: tim8es/", text)
        for legacy in [
            "check.yml", "ff-private-tests.yml", "ff-qwen-private.yml",
            "ff-voice-profile-preflight.yml", "render-short.yml", "runner-test.yml",
        ]:
            self.assertTrue((root / ".github/workflows" / legacy).exists())


if __name__ == "__main__":
    unittest.main()
