import re
import unittest
from pathlib import Path


class RenderWorkflowContract(unittest.TestCase):
    def test_render_workflow_uses_secret_pinned_source_and_opaque_input(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "render-short.yml").read_text()
        dispatch = workflow.split("workflow_dispatch:", 1)[1].split("\npermissions:", 1)[0]

        self.assertEqual(len(re.findall(r"^      [a-z_]+:$", dispatch, re.M)), 1)
        self.assertIn("job_id:", dispatch)
        self.assertIn("permissions: {}", workflow)
        self.assertIn("ref: ${{ secrets.PRIVATE_RENDERER_REF }}", workflow)
        self.assertIn("^[0-9a-f]{40}$", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s+ref:\s+[0-9a-f]{40}\s*$")
        self.assertNotIn("upload-artifact", workflow)


    def test_render_dependencies_keep_runner_apt_failover_defaults(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "render-short.yml").read_text()
        install = workflow.split("      - name: Install renderer dependencies", 1)[1].split(
            "      - name: Report renderer setup failure", 1
        )[0]

        self.assertIn("sudo apt-get -o Acquire::ForceIPv4=true update", install)
        self.assertNotRegex(install, r"Acquire::(?:http::Timeout|https::Timeout|Retries)=")

if __name__ == "__main__":
    unittest.main()
