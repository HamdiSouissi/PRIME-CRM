"""Read-only Netlify diagnostics use mocked data with network access blocked."""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from tools.netlify_lock_diagnostic import (
    DiagnosticError,
    boolean_state,
    main,
    published_state,
    run_diagnostic,
    validate_context,
)
from tools.netlify_preflight import SITE_API_URL, SITE_ID, SITE_NAME

TOKEN = "fake-netlify-token-never-print"
DEPLOY_ID = "fake-deploy-id-never-print"
CONTEXT = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REPOSITORY": "HamdiSouissi/PRIME-CRM",
    "GITHUB_REF": "refs/heads/arena/a18b007f-prime-crm",
    "NETLIFY_LOCK_DIAGNOSTIC_APPROVED": "true",
    "NETLIFY_AUTH_TOKEN": TOKEN,
}
SITE = {
    "id": SITE_ID,
    "name": SITE_NAME,
    "build_settings": {"stop_builds": True, "env": {"SECRET": TOKEN}},
    "prevent_non_git_prod_deploys": False,
    "published_deploy": {"id": DEPLOY_ID, "locked": False},
    "default_hooks_data": {"access_token": TOKEN},
}
DETAIL = {"id": DEPLOY_ID, "site_id": SITE_ID, "draft": False, "locked": False}


def response(body: object, status: int = 200) -> Mock:
    result = Mock()
    result.getcode.return_value = status
    result.read.return_value = json.dumps(body).encode()
    context = Mock()
    context.__enter__ = Mock(return_value=result)
    context.__exit__ = Mock(return_value=False)
    return context


class NetlifyLockDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("socket.socket", side_effect=AssertionError("network access is forbidden in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_context_requires_approved_exact_push(self) -> None:
        validate_context(CONTEXT)
        for key in (
            "GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_REPOSITORY", "GITHUB_REF", "NETLIFY_LOCK_DIAGNOSTIC_APPROVED"
        ):
            for value in ("", "unexpected"):
                with self.subTest(key=key, value=value), self.assertRaises(DiagnosticError):
                    validate_context({**CONTEXT, key: value})

    def test_boolean_categories_do_not_coerce_values(self) -> None:
        for value, expected in ((True, "true"), (False, "false"), (None, "null"), (0, "invalid"), (TOKEN, "invalid")):
            with self.subTest(value=value):
                self.assertEqual(boolean_state({"locked": value}, "locked"), expected)
        self.assertEqual(boolean_state({}, "locked"), "absent")
        self.assertEqual(boolean_state(None, "locked"), "unavailable")

    def test_published_deploy_categories_reject_unsafe_ids(self) -> None:
        cases = (
            ({}, ("absent", "unavailable", None)),
            ({"published_deploy": None}, ("null", "unavailable", None)),
            ({"published_deploy": TOKEN}, ("invalid", "unavailable", None)),
            ({"published_deploy": {}}, ("object", "absent", None)),
            ({"published_deploy": {"id": "../other"}}, ("object", "invalid", None)),
            ({"published_deploy": {"id": DEPLOY_ID}}, ("object", "valid", DEPLOY_ID)),
        )
        for site, expected in cases:
            with self.subTest(site=site):
                self.assertEqual(published_state(site), expected)

    def test_two_requests_are_authenticated_gets_to_fixed_project(self) -> None:
        opener = Mock()
        opener.open.side_effect = [response(SITE), response(DETAIL)]
        report = run_diagnostic(TOKEN, opener)
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual([request.get_method() for request in requests], ["GET", "GET"])
        self.assertEqual(requests[0].full_url, SITE_API_URL)
        self.assertEqual(requests[1].full_url, f"{SITE_API_URL}/deploys/{DEPLOY_ID}")
        for request in requests:
            self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
            self.assertNotIn(TOKEN, request.full_url)
        self.assertEqual(report["PROJECT_MATCH"], "yes")
        self.assertEqual(report["STOPPED_BUILDS"], "true")
        self.assertEqual(report["PREVENT_NON_GIT_PROD_DEPLOYS"], "false")
        self.assertEqual(report["PUBLISHED_DEPLOY_ID"], "valid")
        self.assertEqual(report["PUBLISHED_DEPLOY_LOCKED"], "false")
        self.assertEqual(report["DEPLOY_DETAIL"], "available")
        self.assertEqual(report["DEPLOY_DETAIL_LOCKED"], "false")
        self.assertNotIn(TOKEN, str(report))
        self.assertNotIn(DEPLOY_ID, str(report))

    def test_missing_fields_and_mismatched_project_never_leak_values(self) -> None:
        site = {
            "id": "different-project",
            "name": TOKEN,
            "build_settings": {"stop_builds": True},
            "published_deploy": {"id": DEPLOY_ID},
        }
        opener = Mock()
        opener.open.return_value = response(site)
        report = run_diagnostic(TOKEN, opener)
        opener.open.assert_called_once()
        self.assertEqual(report["PROJECT_MATCH"], "no")
        self.assertEqual(report["PREVENT_NON_GIT_PROD_DEPLOYS"], "absent")
        self.assertEqual(report["PUBLISHED_DEPLOY_LOCKED"], "absent")
        self.assertEqual(report["DEPLOY_DETAIL"], "not_checked")
        self.assertNotIn(TOKEN, str(report))
        self.assertNotIn(DEPLOY_ID, str(report))

    def test_invalid_id_skips_second_request(self) -> None:
        opener = Mock()
        opener.open.return_value = response({**SITE, "published_deploy": {"id": "../other"}})
        report = run_diagnostic(TOKEN, opener)
        opener.open.assert_called_once()
        self.assertEqual(report["PUBLISHED_DEPLOY_ID"], "invalid")
        self.assertEqual(report["DEPLOY_DETAIL"], "not_checked")

    def test_failed_detail_is_sanitized_and_not_retried(self) -> None:
        for error in (URLError(TOKEN), HTTPError(SITE_API_URL, 302, TOKEN, {"Location": "https://example.invalid"}, None)):
            opener = Mock()
            opener.open.side_effect = [response(SITE), error]
            report = run_diagnostic(TOKEN, opener)
            self.assertEqual(opener.open.call_count, 2)
            self.assertEqual(report["DEPLOY_DETAIL"], "unavailable")
            self.assertNotIn(TOKEN, str(report))

    def test_main_outputs_only_fixed_labels_and_never_secrets_or_ids(self) -> None:
        opener = Mock()
        opener.open.side_effect = [response(SITE), response(DETAIL)]
        output = io.StringIO()
        with (
            patch.dict(os.environ, CONTEXT, clear=True),
            patch("tools.netlify_lock_diagnostic.make_opener", return_value=opener),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(), 0)
        self.assertIn("NO_DEPLOYMENT_OR_SETTINGS_CHANGE=yes", output.getvalue())
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertNotIn(DEPLOY_ID, output.getvalue())
        self.assertNotIn(SITE_ID, output.getvalue())

    def test_missing_context_or_token_never_opens_a_connection(self) -> None:
        for context in ({}, {**CONTEXT, "NETLIFY_AUTH_TOKEN": ""}):
            error = io.StringIO()
            with (
                self.subTest(context=context),
                patch.dict(os.environ, context, clear=True),
                patch("tools.netlify_lock_diagnostic.make_opener") as opener,
                contextlib.redirect_stderr(error),
            ):
                self.assertEqual(main(), 1)
                opener.assert_not_called()
                self.assertNotIn(TOKEN, error.getvalue())

    def test_unexpected_error_never_echoes_sensitive_exception(self) -> None:
        error = io.StringIO()
        with (
            patch.dict(os.environ, CONTEXT, clear=True),
            patch("tools.netlify_lock_diagnostic.make_opener", side_effect=RuntimeError(TOKEN)),
            contextlib.redirect_stderr(error),
        ):
            self.assertEqual(main(), 1)
        self.assertIn("no deployment or configuration change", error.getvalue())
        self.assertNotIn(TOKEN, error.getvalue())


if __name__ == "__main__":
    unittest.main()
