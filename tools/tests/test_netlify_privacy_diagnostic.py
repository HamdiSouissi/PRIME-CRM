"""Anonymous diagnostic tests; no real connections or credentials."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from tools.netlify_preflight import PUBLIC_LOGIN_URL, SITE_HOST, SITE_ID
from tools.netlify_privacy_diagnostic import describe_response, main

FAKE_SECRET = "fake-secret-do-not-output"
GATE = "https://app.netlify.com/edge-access?" + urlencode(
    {"domain": SITE_HOST, "requested_path": "/login", "site_id": SITE_ID}
)


class NetlifyPrivacyDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("socket.socket", side_effect=AssertionError("network access is forbidden in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matching_redirect_prints_only_fixed_flags(self) -> None:
        summary = describe_response(302, GATE)
        self.assertIn("HTTP:302", summary)
        for key in ("location", "https", "host", "path", "fragment", "query", "domain", "site", "login", "match"):
            self.assertIn(f"{key}:1", summary)
        self.assertNotIn(GATE, summary)
        self.assertNotIn(SITE_ID, summary)
        self.assertNotIn(SITE_HOST, summary)

    def test_unexpected_redirect_or_http_response_never_passes(self) -> None:
        self.assertIn("HTTP:200;location:0", describe_response(200, ""))
        self.assertIn("match:0", describe_response(200, GATE))
        self.assertIn("host:0", describe_response(302, GATE.replace("app.netlify.com", "attacker.example")))
        self.assertIn("site:0", describe_response(302, GATE.replace(SITE_ID, "another-site")))
        self.assertIn("login:0", describe_response(302, GATE.replace("%2Flogin", "%2Fother")))
        self.assertIn("query:0", describe_response(302, GATE + "&malformed"))
        self.assertIn("match:0", describe_response(302, GATE + "#fragment"))
        self.assertIn("match:0", describe_response(302, "https://[bad-ipv6"))
        self.assertEqual(describe_response("302", GATE), "invalid-response")
        self.assertEqual(describe_response(True, GATE), "invalid-response")

    def test_arbitrary_response_values_are_never_in_the_summary(self) -> None:
        summary = describe_response(302, f"https://{FAKE_SECRET}.invalid/{FAKE_SECRET}?token={FAKE_SECRET}#{FAKE_SECRET}")
        self.assertNotIn(FAKE_SECRET, summary)
        self.assertIn("match:0", summary)

    def test_one_anonymous_get_and_no_redirect_following(self) -> None:
        opener = Mock()
        opener.open.side_effect = HTTPError(PUBLIC_LOGIN_URL, 302, "redirect", {"Location": GATE}, None)
        out = io.StringIO()
        with (
            patch.dict(os.environ, {"NETLIFY_AUTH_TOKEN": FAKE_SECRET}),
            patch("tools.netlify_privacy_diagnostic.make_opener", return_value=opener),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(main(), 0)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, PUBLIC_LOGIN_URL)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)
        self.assertIn("HTTP:302", out.getvalue())
        self.assertIn("match:1", out.getvalue())
        self.assertNotIn(FAKE_SECRET, out.getvalue())
        self.assertNotIn(GATE, out.getvalue())

    def test_network_errors_are_sanitized_and_not_retried(self) -> None:
        opener = Mock()
        opener.open.side_effect = URLError(f"unexpected {FAKE_SECRET}")
        out = io.StringIO()
        with patch("tools.netlify_privacy_diagnostic.make_opener", return_value=opener), contextlib.redirect_stdout(out):
            self.assertEqual(main(), 0)
        opener.open.assert_called_once()
        self.assertEqual(out.getvalue(), "observation=probe-error\n")
        self.assertNotIn(FAKE_SECRET, out.getvalue())


if __name__ == "__main__":
    unittest.main()
