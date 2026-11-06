"""No secrets, repos, private APIs or customer data in test fixtures."""
import io
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from runner.verify import verify, main


class GenericBootstrapTests(unittest.TestCase):
    def test_valid_bootstrap_and_optional_empty_environment(self):
        settings = {"TASK_RUNNER_REGISTRY": "example/private",
                    "TASK_RUNNER_ACCESS_TOKEN": "opaque_value",
                    "TASK_RUNNER_ENV_JSON": '{"key":"value"}'}
        self.assertEqual(verify(settings), "READY")
        settings["TASK_RUNNER_ENV_JSON"] = ""
        self.assertEqual(verify(settings), "EMPTY_PRIVATE_ENV_MAP")

    def test_all_errors_are_generic_and_redacted(self):
        fixture = {"TASK_RUNNER_REGISTRY": "example/private",
                   "TASK_RUNNER_ACCESS_TOKEN": "not-to-print",
                   "TASK_RUNNER_ENV_JSON": '{"x": "secret-value"}'}
        for updates, expected in [
            ({"TASK_RUNNER_REGISTRY": ""}, "MISSING_BOOTSTRAP"),
            ({"TASK_RUNNER_ACCESS_TOKEN": ""}, "MISSING_BOOTSTRAP"),
            ({"TASK_RUNNER_REGISTRY": "not a slug"}, "INVALID_BOOTSTRAP"),
            ({"TASK_RUNNER_ENV_JSON": "{"}, "INVALID_BOOTSTRAP"),
            ({"TASK_RUNNER_ENV_JSON": '{"x":null}'}, "INVALID_BOOTSTRAP"),
        ]:
            cfg = {**fixture, **updates}
            self.assertEqual(verify(cfg), expected)
            out, err = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, cfg, clear=True), \
                 redirect_stdout(out), redirect_stderr(err), \
                 self.assertRaises(SystemExit):
                main()
            self.assertNotIn("secret-value", err.getvalue())
            self.assertNotIn("not-to-print", err.getvalue())
            self.assertNotIn("example/private", err.getvalue())
            self.assertIn(expected, err.getvalue())

    def test_workflow_checks_before_execute(self):
        from pathlib import Path
        workflow = (Path(__file__).parents[1] / ".github/workflows/queued.yml").read_text()
        self.assertLess(workflow.index("runner.verify"),
                        workflow.index("runner.execute"))
        self.assertIn("permissions: {}", workflow)


if __name__ == "__main__":
    unittest.main()
