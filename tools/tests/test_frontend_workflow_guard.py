"""Static assertions for the opt-in production workflow; no network access."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools.netlify_release import validate_context

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def job(source: str, name: str) -> str:
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z_]+:\n|\Z)", source, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"Missing job: {name}")
    return match.group(1)


class FrontendWorkflowGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = WORKFLOW.read_text(encoding="utf-8")
        self.release = job(self.source, "request_netlify_deploy")
        self.render = job(self.source, "request_render_deploy")

    def test_real_release_requires_both_markers_branch_ci_and_approval(self) -> None:
        required = (
            "github.event_name == 'push'",
            "github.repository == 'HamdiSouissi/PRIME-CRM'",
            "github.ref == 'refs/heads/arena/a18b007f-prime-crm'",
            "contains(github.event.head_commit.message, '[frontend release]')",
            "contains(github.event.head_commit.message, '[skip render]')",
            "needs: [backend, frontend]",
            "name: production-frontend",
            "deployment: false",
            "fetch-depth: 0",
            "persist-credentials: false",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.release)
        self.assertIn("!contains(github.event.head_commit.message, '[frontend release]')", self.render)

    def test_guards_and_build_run_before_secret_release_step(self) -> None:
        locations = [
            self.release.index(part)
            for part in (
                "tools/migration_fingerprint.py verify",
                "python -m tools.backend_release_guard",
                "docker build --target verified-static",
                "python -m tools.frontend_release",
                "NETLIFY_AUTH_TOKEN: ${{ secrets.NETLIFY_AUTH_TOKEN }}",
                "python -m tools.netlify_release",
            )
        ]
        self.assertEqual(locations, sorted(locations))
        self.assertEqual(self.release.count("${{ secrets.NETLIFY_AUTH_TOKEN }}"), 1)
        self.assertNotIn("secrets.", self.release[: locations[-2]])
        self.assertIn("GH_READ_TOKEN: ${{ github.token }}", self.release)
        self.assertNotIn("continue-on-error", self.release)
        self.assertNotIn("upload-artifact", self.release)

    def test_workflow_approval_flag_matches_release_context(self) -> None:
        match = re.search(r"NETLIFY_RELEASE_APPROVED: '([^']+)'", self.release)
        self.assertIsNotNone(match)
        context = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REPOSITORY": "HamdiSouissi/PRIME-CRM",
            "GITHUB_REF": "refs/heads/arena/a18b007f-prime-crm",
            "GITHUB_SHA": "a" * 40,
            "NETLIFY_RELEASE_APPROVED": match.group(1),
        }
        self.assertEqual(validate_context(context), "a" * 40)


if __name__ == "__main__":
    unittest.main()
