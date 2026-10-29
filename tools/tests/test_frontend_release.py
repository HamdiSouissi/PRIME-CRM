"""The frontend packaging guard uses fictitious files and never accesses a network."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from tools.frontend_release import InvalidFrontendBuild, PUBLIC_API_ORIGIN, main, prepare_archive

COMMIT = "0123456789abcdef" * 2 + "01234567"
HEADERS = """/*
  X-Frame-Options: DENY
  Content-Security-Policy: frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/build-info.json
  Cache-Control: no-store
"""


class FrontendReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dist = self.root / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
        (self.dist / "_redirects").write_text("/* /index.html 200\n", encoding="utf-8")
        (self.dist / "_headers").write_text(HEADERS, encoding="utf-8")
        (self.dist / "assets/app.js").write_text(f'const url = "{PUBLIC_API_ORIGIN}";', encoding="utf-8")
        self.output = self.root / "release.zip"
        patcher = patch("socket.socket", side_effect=AssertionError("network access is forbidden in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self, commit: str = COMMIT, origin: str = PUBLIC_API_ORIGIN) -> None:
        prepare_archive(self.dist, self.output, commit, origin)

    def assert_rejected(self, commit: str = COMMIT, origin: str = PUBLIC_API_ORIGIN) -> None:
        with self.assertRaises(InvalidFrontendBuild):
            self.prepare(commit, origin)
        self.assertFalse(self.output.exists())

    def test_packages_static_files_at_root_and_records_exact_commit(self) -> None:
        self.prepare()
        with ZipFile(self.output) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"index.html", "_redirects", "_headers", "assets/app.js", "build-info.json"},
            )
            self.assertIsNone(archive.testzip())
            self.assertEqual(json.loads(archive.read("build-info.json")), {"commit": COMMIT})
            self.assertIn(PUBLIC_API_ORIGIN.encode(), archive.read("assets/app.js"))

    def test_zip_is_reproducible_for_identical_content(self) -> None:
        self.prepare()
        first = hashlib.sha256(self.output.read_bytes()).hexdigest()
        another = self.root / "another.zip"
        prepare_archive(self.dist, another, COMMIT, PUBLIC_API_ORIGIN)
        self.assertEqual(first, hashlib.sha256(another.read_bytes()).hexdigest())

    def test_invalid_commit_or_api_origin_is_rejected(self) -> None:
        for commit in ("", "HEAD", COMMIT.upper(), COMMIT[:-1], COMMIT + "0"):
            with self.subTest(commit=commit):
                self.assert_rejected(commit=commit)
        for origin in ("", "https://wrong.example", PUBLIC_API_ORIGIN + "/", "http://prime-crm-cqi3.onrender.com"):
            with self.subTest(origin=origin):
                self.assert_rejected(origin=origin)

    def test_missing_or_wrong_redirect_and_index_are_rejected(self) -> None:
        (self.dist / "_redirects").write_text("/* https://other.example 302\n", encoding="utf-8")
        self.assert_rejected()
        (self.dist / "_redirects").write_text("/* /index.html 200\n", encoding="utf-8")
        (self.dist / "index.html").unlink()
        self.assert_rejected()

    def test_security_headers_must_apply_to_correct_paths(self) -> None:
        for replacement in (
            HEADERS.replace("X-Frame-Options: DENY", "X-Frame-Options: SAMEORIGIN"),
            HEADERS.replace("frame-ancestors 'none'", "frame-ancestors *"),
            HEADERS.replace("  Cache-Control: no-store", "  Cache-Control: public"),
            HEADERS.replace("/build-info.json", "/wrong.json"),
            HEADERS.replace("/*", "/wrong"),
            HEADERS + "  Cache-Control: no-store\n",
        ):
            with self.subTest(headers=replacement):
                (self.dist / "_headers").write_text(replacement, encoding="utf-8")
                self.assert_rejected()

    def test_javascript_must_reference_origin_and_be_used_by_index(self) -> None:
        js = self.dist / "assets/app.js"
        js.write_text('const url = "https://wrong.example";', encoding="utf-8")
        self.assert_rejected()
        js.write_text(f'const url = "{PUBLIC_API_ORIGIN}";', encoding="utf-8")
        (self.dist / "index.html").write_text("<html>No script</html>", encoding="utf-8")
        self.assert_rejected()

    def test_hidden_sensitive_reserved_and_unsafe_files_are_rejected(self) -> None:
        for filename in (".env", "secret.pem", "secret.key", "data.dump", "build-info.json", "back\\slash.js"):
            path = self.dist / filename
            path.write_text("fake value", encoding="utf-8")
            with self.subTest(filename=filename):
                self.assert_rejected()
            path.unlink()
        hidden = self.dist / ".hidden"
        hidden.mkdir()
        self.assert_rejected()

    def test_file_and_directory_symlinks_are_rejected(self) -> None:
        link = self.dist / "assets" / "link.js"
        link.symlink_to(self.dist / "assets/app.js")
        self.assert_rejected()
        link.unlink()
        (self.dist / "linked-directory").symlink_to(self.dist / "assets", target_is_directory=True)
        self.assert_rejected()

    def test_root_symlink_and_missing_root_are_rejected(self) -> None:
        linked = self.root / "linked-dist"
        linked.symlink_to(self.dist, target_is_directory=True)
        for root in (linked, self.root / "missing"):
            with self.subTest(root=root), self.assertRaises(InvalidFrontendBuild):
                prepare_archive(root, self.output, COMMIT, PUBLIC_API_ORIGIN)
        self.assertFalse(self.output.exists())

    def test_rejects_output_inside_build_and_wrong_extension(self) -> None:
        for output in (self.dist / "release.zip", self.root / "release.txt"):
            with self.subTest(output=output), self.assertRaises(InvalidFrontendBuild):
                prepare_archive(self.dist, output, COMMIT, PUBLIC_API_ORIGIN)
            self.assertFalse(output.exists())

    def test_size_and_file_count_limits_fail_before_creating_archive(self) -> None:
        with patch("tools.frontend_release._MAX_TOTAL_BYTES", 4):
            self.assert_rejected()
        with patch("tools.frontend_release._MAX_FILES", 1):
            self.assert_rejected()

    def test_non_regular_file_is_rejected(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO unavailable")
        os.mkfifo(self.dist / "pipe")
        self.assert_rejected()

    def test_cli_reports_failure_without_echoing_inputs(self) -> None:
        error, output = io.StringIO(), io.StringIO()
        arguments = [
            "frontend_release", "--dist", str(self.dist), "--output", str(self.output),
            "--commit", "fake-sensitive-input", "--api-origin", PUBLIC_API_ORIGIN,
        ]
        with patch("sys.argv", arguments), contextlib.redirect_stderr(error), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertNotIn("fake-sensitive-input", error.getvalue() + output.getvalue())
        self.assertIn("nothing was published", error.getvalue())
        self.assertFalse(self.output.exists())

    def test_cli_success_says_nothing_was_published(self) -> None:
        output = io.StringIO()
        arguments = [
            "frontend_release", "--dist", str(self.dist), "--output", str(self.output),
            "--commit", COMMIT, "--api-origin", PUBLIC_API_ORIGIN,
        ]
        with patch("sys.argv", arguments), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertIn("nothing was published", output.getvalue())
        self.assertTrue(self.output.exists())


if __name__ == "__main__":
    unittest.main()
