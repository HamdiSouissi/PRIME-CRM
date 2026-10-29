"""Offline tests with fictitious hook strings only; no network access."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest.mock import patch

from tools.render_hook_check import InvalidHook, main, validate_hook


class RenderHookCheckTests(unittest.TestCase):
    def test_accepts_documented_shape_with_fictitious_keys(self) -> None:
        with patch("socket.socket", side_effect=AssertionError("network access is forbidden")):
            validate_hook("https://api.render.com/deploy/srv-Abc123?key=fake-hook-key")
            validate_hook("https://api.render.com/deploy/srv-123?key=fake%2Fkey%3D")

    def test_rejects_missing_unsafe_or_unexpected_shapes(self) -> None:
        invalid_values = (
            "",
            "http://api.render.com/deploy/srv-123?key=fake",
            "https://not-render.example/deploy/srv-123?key=fake",
            "https://api.render.com.evil.example/deploy/srv-123?key=fake",
            "https://api.render.com@evil.example/deploy/srv-123?key=fake",
            "https://api.render.com:443/deploy/srv-123?key=fake",
            "https://api.render.com/deploy/another-123?key=fake",
            "https://api.render.com/deploy/srv-123/extra?key=fake",
            "https://api.render.com/deploy/srv-123?key=",
            "https://api.render.com/deploy/srv-123?key=fake&ref=old",
            "https://api.render.com/deploy/srv-123?key=fake&key=other",
            "https://api.render.com/deploy/srv-123?key=fake#fragment",
            "https://api.render.com/deploy/srv-123?key=fake;ref=old",
            "https://api.render.com/deploy/srv-123?key=fake%0Avalue",
            " https://api.render.com/deploy/srv-123?key=fake",
            "https://api.render.com/deploy/srv-123?key=é",
        )
        with patch("socket.socket", side_effect=AssertionError("network access is forbidden")):
            for value in invalid_values:
                with self.subTest(value=value), self.assertRaises(InvalidHook) as error:
                    validate_hook(value)
                if value:
                    self.assertNotIn(value, str(error.exception))

    def test_cli_never_prints_the_value_and_does_not_make_requests(self) -> None:
        fake_secret = "fictitious-do-not-print-this-key"
        good = f"https://api.render.com/deploy/srv-Test123?key={fake_secret}"
        bad = f"https://api.render.com/deploy/srv-Test123?key={fake_secret}&ref=old"
        with patch("socket.socket", side_effect=AssertionError("network access is forbidden")):
            for value, expected_result in ((good, 0), (bad, 1), ("", 1)):
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    self.subTest(expected_result=expected_result),
                    patch.dict(os.environ, {"RENDER_DEPLOY_HOOK_URL": value}),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(main(), expected_result)
                self.assertNotIn(fake_secret, stdout.getvalue() + stderr.getvalue())
                self.assertIn("no request was sent", (stdout.getvalue() + stderr.getvalue()).lower())


if __name__ == "__main__":
    unittest.main()
