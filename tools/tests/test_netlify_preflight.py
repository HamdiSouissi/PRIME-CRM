"""Netlify preflight tests use mocked responses; sockets are always disabled."""

from __future__ import annotations

import contextlib
import io
import json
import os
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler

from tools.netlify_preflight import (
    NoRedirect,
    PreflightError,
    PUBLIC_LOGIN_URL,
    SITE_API_URL,
    SITE_HOST,
    SITE_ID,
    SITE_NAME,
    _MAX_RESPONSE_BYTES,
    check_private_login,
    get_site,
    is_private_redirect,
    main,
    make_opener,
    run_preflight,
    validate_site,
    validate_token,
)

TOKEN = "fake-netlify-token-never-print"
GATE = "https://app.netlify.com/edge-access?" + urlencode(
    {"domain": SITE_HOST, "requested_path": "/login", "site_id": SITE_ID}
)
SITE = {
    "id": SITE_ID,
    "name": SITE_NAME,
    "build_settings": {"stop_builds": True, "env": {"MUST_NOT_BE_PRINTED": TOKEN}},
    "published_deploy": {"id": "fake-deploy", "locked": False},
    "default_hooks_data": {"access_token": TOKEN},
    "prevent_non_git_prod_deploys": False,
}


def response(body: bytes, status: int = 200):
    result = Mock()
    result.getcode.return_value = status
    result.read.return_value = body
    result.headers = {}
    context = Mock()
    context.__enter__ = Mock(return_value=result)
    context.__exit__ = Mock(return_value=False)
    return context


def gate_error(location: str = GATE, code: int = 302) -> HTTPError:
    return HTTPError(PUBLIC_LOGIN_URL, code, "redirect", {"Location": location}, None)


class NetlifyPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("socket.socket", side_effect=AssertionError("network access is forbidden in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_preflight_makes_only_two_gets_and_token_is_not_sent_to_site(self) -> None:
        opener = Mock()
        opener.open.side_effect = [response(json.dumps(SITE).encode()), gate_error()]
        run_preflight(TOKEN, opener)
        self.assertEqual(opener.open.call_count, 2)
        first, second = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(first.get_method(), "GET")
        self.assertEqual(first.full_url, SITE_API_URL)
        self.assertEqual(first.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, first.full_url)
        self.assertEqual(second.get_method(), "GET")
        self.assertEqual(second.full_url, PUBLIC_LOGIN_URL)
        self.assertIsNone(second.get_header("Authorization"))
        self.assertEqual([call.kwargs["timeout"] for call in opener.open.call_args_list], [20, 20])

    def test_token_validation_rejects_whitespace_control_or_unexpected_characters(self) -> None:
        validate_token(TOKEN)
        validate_token("nfp_abcdefghijklmnopqrstuv==")
        for token in ("", "short", " token-long", "token-long ", "token\r\nInjected", "https://host/secret?x=1", "a" * 513):
            with self.subTest(kind=repr(token[:12])), self.assertRaises(PreflightError) as error:
                validate_token(token)
            if token:
                self.assertNotIn(token, str(error.exception))

    def test_missing_token_never_creates_opener_or_contacts_network(self) -> None:
        error, output = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"NETLIFY_AUTH_TOKEN": ""}),
            patch("tools.netlify_preflight.make_opener") as opener,
            contextlib.redirect_stderr(error),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(), 1)
        opener.assert_not_called()
        self.assertIn("no deployment or configuration change", error.getvalue().lower())

    def test_expected_project_stopped_builds_and_unlocked_deploy_are_required(self) -> None:
        validate_site(SITE)
        invalid_sites = (
            {**SITE, "id": "different"},
            {**SITE, "name": "different"},
            {**SITE, "build_settings": {}},
            {**SITE, "build_settings": {"stop_builds": False}},
            {**SITE, "build_settings": None},
            {**SITE, "prevent_non_git_prod_deploys": True},
            {**SITE, "published_deploy": {"locked": True}},
        )
        for site in invalid_sites:
            with self.subTest(site=site), self.assertRaises(PreflightError):
                validate_site(site)

    def test_unconfirmed_optional_lock_does_not_claim_live_or_publish(self) -> None:
        validate_site({**SITE, "published_deploy": None})
        validate_site({**SITE, "published_deploy": {"id": "fake-deploy"}})

    def test_bad_site_response_or_http_error_is_sanitized(self) -> None:
        cases = (
            response(b"not-json"),
            response(b"[]"),
            response(b"x" * (_MAX_RESPONSE_BYTES + 1)),
            response(json.dumps(SITE).encode(), status=202),
            HTTPError(SITE_API_URL, 401, f"error {TOKEN}", {}, None),
            HTTPError(SITE_API_URL, 302, f"redirect {TOKEN}", {"Location": "https://other.invalid"}, None),
            URLError(f"network {TOKEN}"),
            TimeoutError(f"timeout {TOKEN}"),
        )
        for result in cases:
            opener = Mock()
            opener.open.side_effect = [result] if isinstance(result, Exception) else None
            if not isinstance(result, Exception):
                opener.open.return_value = result
            with self.subTest(kind=type(result).__name__), self.assertRaises(PreflightError) as error:
                get_site(TOKEN, opener)
            opener.open.assert_called_once()
            self.assertNotIn(TOKEN, str(error.exception))

    def test_valid_gate_requires_fixed_https_host_project_and_requested_path(self) -> None:
        self.assertTrue(is_private_redirect(GATE))
        for location in (
            "",
            GATE.replace("https://", "http://"),
            GATE.replace("app.netlify.com", "attacker.example"),
            GATE.replace("/edge-access", "/other"),
            GATE.replace(SITE_ID, "other"),
            GATE.replace(SITE_HOST, "other.netlify.app"),
            GATE.replace("%2Flogin", "%2Fother"),
            GATE + "&site_id=other",
            GATE + "#fragment",
            GATE + "&broken",
        ):
            with self.subTest(location=location):
                self.assertFalse(is_private_redirect(location))

    def test_nonprivate_or_unexpected_responses_fail_closed(self) -> None:
        cases = (
            response(b"public page", status=200),
            gate_error("https://attacker.example/edge-access?" + urlencode({"site_id": SITE_ID})),
            gate_error(GATE, code=401),
            URLError(f"network {TOKEN}"),
        )
        for result in cases:
            opener = Mock()
            opener.open.side_effect = [result] if isinstance(result, Exception) else None
            if not isinstance(result, Exception):
                opener.open.return_value = result
            with self.subTest(kind=type(result).__name__), self.assertRaises(PreflightError) as error:
                check_private_login(opener)
            opener.open.assert_called_once()
            self.assertNotIn(TOKEN, str(error.exception))

    def test_main_sanitizes_failures_even_if_exception_contains_token(self) -> None:
        error, output = io.StringIO(), io.StringIO()
        opener = Mock()
        opener.open.side_effect = URLError(f"network {TOKEN}")
        with (
            patch.dict(os.environ, {"NETLIFY_AUTH_TOKEN": TOKEN}),
            patch("tools.netlify_preflight.make_opener", return_value=opener),
            contextlib.redirect_stderr(error),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(), 1)
        self.assertNotIn(TOKEN, error.getvalue() + output.getvalue())
        self.assertIn("no deployment or configuration change", error.getvalue().lower())

    def test_main_success_is_read_only_and_does_not_echo_response(self) -> None:
        output, error = io.StringIO(), io.StringIO()
        opener = Mock()
        opener.open.side_effect = [response(json.dumps(SITE).encode()), gate_error()]
        with (
            patch.dict(os.environ, {"NETLIFY_AUTH_TOKEN": TOKEN}),
            patch("tools.netlify_preflight.make_opener", return_value=opener),
            contextlib.redirect_stderr(error),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(), 0)
        self.assertNotIn(TOKEN, output.getvalue() + error.getvalue())
        self.assertIn("read-only", output.getvalue().lower())
        self.assertIn("no deployment or configuration change", output.getvalue().lower())

    def test_opener_disables_proxy_redirect_and_tls_key_logging(self) -> None:
        opener = make_opener()
        self.assertTrue(any(isinstance(handler, NoRedirect) for handler in opener.handlers))
        proxies = [handler for handler in opener.handlers if isinstance(handler, ProxyHandler)]
        # An empty ProxyHandler is omitted by urllib when it has no schemes.
        self.assertTrue(all(handler.proxies == {} for handler in proxies))
        https = next(handler for handler in opener.handlers if isinstance(handler, HTTPSHandler))
        context = https._context
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIsNone(context.keylog_filename)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid"))


if __name__ == "__main__":
    unittest.main()
