"""Release-request tests use fake hooks and mocked HTTP responses only."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from tools.render_deploy import InvalidRelease, NoRedirect, build_request, main, request_deploy

FAKE_KEY = "fictitious-secret-never-log"
FAKE_HOOK = f"https://api.render.com/deploy/srv-Fake123?key={FAKE_KEY}"
COMMIT = "0123456789abcdef" * 2 + "01234567"


class RenderDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("socket.socket", side_effect=AssertionError("network access is forbidden in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_request_is_post_and_pinned_to_exact_full_commit(self) -> None:
        request = build_request(FAKE_HOOK, COMMIT)
        parts = urlsplit(request.full_url)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parts.netloc, "api.render.com")
        self.assertEqual(parts.path, "/deploy/srv-Fake123")
        self.assertEqual(parse_qs(parts.query), {"key": [FAKE_KEY], "ref": [COMMIT]})

    def test_invalid_hook_or_commit_is_rejected_without_printing_input(self) -> None:
        for hook, commit in (
            ("", COMMIT),
            ("https://other.example/deploy/srv-Fake123?key=fake", COMMIT),
            (FAKE_HOOK, "HEAD"),
            (FAKE_HOOK, COMMIT.upper()),
            (FAKE_HOOK, "a" * 39),
            (FAKE_HOOK + "&ref=old", COMMIT),
        ):
            with self.subTest(hook=hook != "", commit=commit != ""), self.assertRaises(InvalidRelease) as error:
                build_request(hook, commit)
            self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_valid_request_is_sent_once_and_reports_acceptance_not_live(self) -> None:
        for status, expected in ((200, "accepted"), (202, "queued")):
            response = Mock()
            response.getcode.return_value = status
            context = Mock()
            context.__enter__ = Mock(return_value=response)
            context.__exit__ = Mock(return_value=False)
            opener = Mock()
            opener.open.return_value = context
            output = io.StringIO()
            with self.subTest(status=status), contextlib.redirect_stdout(output):
                self.assertEqual(request_deploy(build_request(FAKE_HOOK, COMMIT), opener), 0)
            opener.open.assert_called_once()
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)
            self.assertIn(expected, output.getvalue().lower())
            self.assertIn("verify", output.getvalue().lower())
            self.assertNotIn(FAKE_KEY, output.getvalue())

    def test_rejection_or_uncertain_transport_never_leaks_or_retries(self) -> None:
        for error in (
            HTTPError(FAKE_HOOK, 401, f"error with {FAKE_KEY}", {}, None),
            HTTPError(FAKE_HOOK, 302, f"redirect {FAKE_KEY}", {}, None),
            URLError(f"connection failed {FAKE_KEY}"),
            TimeoutError(f"request timed out {FAKE_KEY}"),
            RuntimeError(f"unexpected failure {FAKE_KEY}"),
        ):
            opener = Mock()
            opener.open.side_effect = error
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(kind=type(error).__name__), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(request_deploy(build_request(FAKE_HOOK, COMMIT), opener), 1)
            opener.open.assert_called_once()
            self.assertNotIn(FAKE_KEY, out.getvalue() + err.getvalue())
            self.assertIn("check render before retrying", err.getvalue().lower())

    def test_main_does_not_send_if_configuration_missing(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"RENDER_DEPLOY_HOOK_URL": "", "GITHUB_SHA": COMMIT}),
            patch("tools.render_deploy.build_opener") as opener,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            self.assertEqual(main(), 1)
        opener.assert_not_called()
        self.assertIn("no request was sent", err.getvalue())

    def test_main_disables_proxies_and_redirects(self) -> None:
        response = Mock()
        response.getcode.return_value = 200
        response_context = Mock()
        response_context.__enter__ = Mock(return_value=response)
        response_context.__exit__ = Mock(return_value=False)
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"RENDER_DEPLOY_HOOK_URL": FAKE_HOOK, "GITHUB_SHA": COMMIT}),
            patch("tools.render_deploy.build_opener") as build_opener,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            build_opener.return_value.open.return_value = response_context
            self.assertEqual(main(), 0)
        proxy, redirects = build_opener.call_args.args
        self.assertEqual(proxy.proxies, {})
        self.assertIsInstance(redirects, NoRedirect)
        build_opener.return_value.open.assert_called_once()
        self.assertNotIn(FAKE_KEY, out.getvalue() + err.getvalue())

    def test_redirect_handler_refuses_redirect(self) -> None:
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid"))


if __name__ == "__main__":
    unittest.main()
