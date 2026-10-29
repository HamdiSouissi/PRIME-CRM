"""Backend release guard tests use isolated Git repositories, never Render."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.backend_release_guard import BackendGuardError, main, verify_backend_tree


class BackendReleaseGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI Test")
        self.git("config", "user.email", "ci@example.invalid")
        (self.repo / "backend").mkdir()
        (self.repo / "backend" / "app.py").write_text("version = 1\n", encoding="utf-8")
        self.git("add", "backend/app.py")
        self.git("commit", "-qm", "backend baseline")
        self.baseline = self.git("rev-parse", "HEAD")
        (self.repo / "README.md").write_text("frontend change\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "unrelated change")
        self.same_tree = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_unrelated_change_keeps_backend_tree_compatible(self) -> None:
        verify_backend_tree(self.repo, tested_commit=self.same_tree, live_commit=self.baseline)
        verify_backend_tree(self.repo, tested_commit=self.baseline, live_commit=self.baseline)

    def test_changed_backend_is_rejected(self) -> None:
        (self.repo / "backend" / "app.py").write_text("version = 2\n", encoding="utf-8")
        self.git("add", "backend/app.py")
        self.git("commit", "-qm", "backend change")
        with self.assertRaises(BackendGuardError):
            verify_backend_tree(self.repo, tested_commit=self.git("rev-parse", "HEAD"), live_commit=self.baseline)

    def test_equal_tree_from_unrelated_commit_is_rejected(self) -> None:
        tree = self.git("rev-parse", f"{self.baseline}^{{tree}}")
        unrelated = self.git("commit-tree", tree, "-m", "unrelated history")
        with self.assertRaises(BackendGuardError):
            verify_backend_tree(self.repo, tested_commit=self.same_tree, live_commit=unrelated)

    def test_invalid_missing_or_nonancestor_commits_fail_closed(self) -> None:
        for value in ("", "HEAD", "x" * 40, "A" * 40, "f" * 40):
            with self.subTest(value=value), self.assertRaises(BackendGuardError):
                verify_backend_tree(self.repo, tested_commit=self.same_tree, live_commit=value)
        with self.assertRaises(BackendGuardError):
            verify_backend_tree(self.repo, tested_commit=self.baseline, live_commit=self.same_tree)

    def test_tag_object_is_not_accepted_as_a_commit(self) -> None:
        self.git("tag", "-a", "test-baseline", self.baseline, "-m", "annotated tag")
        tag = self.git("rev-parse", "refs/tags/test-baseline")
        with self.assertRaises(BackendGuardError):
            verify_backend_tree(self.repo, tested_commit=self.same_tree, live_commit=tag)

    def test_cli_does_not_echo_untrusted_input(self) -> None:
        error = io.StringIO()
        with (
            patch.dict(os.environ, {"GITHUB_SHA": "fake-sensitive-input", "PRODUCTION_BACKEND_COMMIT": self.baseline}),
            contextlib.redirect_stderr(error),
        ):
            self.assertEqual(main(), 1)
        self.assertNotIn("fake-sensitive-input", error.getvalue())
        self.assertIn("no frontend deployment was requested", error.getvalue())


if __name__ == "__main__":
    unittest.main()
