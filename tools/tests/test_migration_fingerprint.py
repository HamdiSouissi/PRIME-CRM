"""Tests use throwaway local Git repositories only; no external services."""

from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.migration_fingerprint import FingerprintError, fingerprint, main, matches


class MigrationFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "--quiet", "--initial-branch=arena/a18b007f-prime-crm")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "ci-fixture@example.invalid")
        self.write("backend/alembic/env.py", "# environment\n")
        self.write("backend/alembic/versions/001.py", "revision = '001'\n")
        self.write("backend/alembic.ini", "[alembic]\n")
        self.write("README.md", "fixture\n")
        self.baseline_commit = self.commit("baseline")
        self.baseline = fingerprint(self.repo, self.baseline_commit)

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def write(self, name: str, contents: str) -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def test_deterministic_and_unrelated_changes_do_not_change_fingerprint(self) -> None:
        self.assertEqual(self.baseline, fingerprint(self.repo, self.baseline_commit))
        self.assertTrue(matches(self.repo, self.baseline_commit, self.baseline))
        self.write("README.md", "unrelated change\n")
        self.assertEqual(self.baseline, fingerprint(self.repo, self.commit("unrelated")))

    def test_adding_or_editing_a_migration_changes_fingerprint(self) -> None:
        self.write("backend/alembic/versions/002.py", "revision = '002'\n")
        added = self.commit("add migration")
        self.assertFalse(matches(self.repo, added, self.baseline))
        self.write("backend/alembic/versions/001.py", "revision = '001'\n# edited\n")
        self.assertNotEqual(fingerprint(self.repo, added), fingerprint(self.repo, self.commit("edit migration")))

    def test_deleting_a_migration_changes_fingerprint(self) -> None:
        (self.repo / "backend/alembic/versions/001.py").unlink()
        self.assertFalse(matches(self.repo, self.commit("delete migration"), self.baseline))

    def test_environment_and_ini_changes_are_detected(self) -> None:
        self.write("backend/alembic/env.py", "# changed environment\n")
        changed_env = self.commit("change environment")
        self.assertFalse(matches(self.repo, changed_env, self.baseline))
        self.write("backend/alembic.ini", "[alembic]\n# changed\n")
        self.assertNotEqual(fingerprint(self.repo, changed_env), fingerprint(self.repo, self.commit("change ini")))

    def test_uncommitted_changes_are_not_used(self) -> None:
        self.write("backend/alembic/env.py", "# uncommitted\n")
        self.assertEqual(self.baseline, fingerprint(self.repo, self.baseline_commit))

    def test_invalid_missing_or_unsafe_inputs_fail_closed(self) -> None:
        for bad_commit in ("HEAD", "a" * 39, "A" * 40, "a" * 40 + ":backend/alembic", "0" * 40):
            with self.subTest(commit=bad_commit), self.assertRaises(FingerprintError):
                fingerprint(self.repo, bad_commit)
        tree_sha = self.git("rev-parse", f"{self.baseline_commit}:backend/alembic")
        with self.assertRaises(FingerprintError):
            fingerprint(self.repo, tree_sha)
        for bad_expected in ("", "a" * 63, "A" * 64, "g" * 64):
            with self.subTest(expected=bad_expected), self.assertRaises(FingerprintError):
                matches(self.repo, self.baseline_commit, bad_expected)

    def test_missing_alembic_tree_and_wrong_object_type_fail_closed(self) -> None:
        for path in (self.repo / "backend/alembic/versions/001.py", self.repo / "backend/alembic/env.py"):
            path.unlink()
        missing = self.commit("remove alembic tree")
        with self.assertRaises(FingerprintError):
            fingerprint(self.repo, missing)
        (self.repo / "backend/alembic/versions").rmdir()
        (self.repo / "backend/alembic").rmdir()
        self.write("backend/alembic", "not a tree\n")
        wrong_type = self.commit("replace tree with file")
        with self.assertRaises(FingerprintError):
            fingerprint(self.repo, wrong_type)

    def test_cli_returns_distinct_exit_codes(self) -> None:
        common = ["--repo", str(self.repo), "--commit", self.baseline_commit]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["verify", *common, "--expected", self.baseline]), 0)
            self.assertEqual(main(["verify", *common, "--expected", "0" * 64]), 1)
            self.assertEqual(main(["verify", *common, "--expected", "invalid"]), 2)
            self.assertEqual(main(["print", *common]), 0)


if __name__ == "__main__":
    unittest.main()
