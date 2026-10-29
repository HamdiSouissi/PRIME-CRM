"""Netlify release tests use fictitious archives and responses; sockets are blocked."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from zipfile import ZipFile

from tools.frontend_release import PUBLIC_API_ORIGIN, prepare_archive
from tools.netlify_preflight import (
    PUBLIC_LOGIN_URL,
    SITE_API_URL,
    SITE_HOST,
    SITE_ID,
    SITE_NAME,
)
from tools.netlify_release import (
    ReleaseNotSent,
    ReleaseOutcomeUnknown,
    ReleasePublishedPrivacyUnknown,
    _safe_archive_name,
    build_upload_request,
    main,
    read_validated_archive,
    release,
    send_upload,
    validate_context,
    validate_release_site,
    wait_for_publication,
)

TOKEN = "fake-netlify-token-never-print"
COMMIT = "0123456789abcdef" * 2 + "01234567"
DEPLOY_ID = "deploy_123456789"
GATE = "https://app.netlify.com/edge-access?" + urlencode(
    {"domain": SITE_HOST, "requested_path": "/login", "site_id": SITE_ID}
)
HEADERS = """/*
  X-Frame-Options: DENY
  Content-Security-Policy: frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/build-info.json
  Cache-Control: no-store
"""
CONTEXT = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REPOSITORY": "HamdiSouissi/PRIME-CRM",
    "GITHUB_REF": "refs/heads/arena/a18b007f-prime-crm",
    "NETLIFY_RELEASE_APPROVED": "true",
    "GITHUB_SHA": COMMIT,
    "NETLIFY_AUTH_TOKEN": TOKEN,
}
SITE = {
    "id": SITE_ID,
    "name": SITE_NAME,
    "build_settings": {"stop_builds": True, "env": {"FAKE_SECRET": TOKEN}},
    "prevent_non_git_prod_deploys": False,
    "published_deploy": {"id": "previous_deploy", "locked": False},
}


def response(data, status: int = 200):
    result = Mock()
    result.getcode.return_value = status
    result.read.return_value = json.dumps(data).encode() if not isinstance(data, bytes) else data
    result.headers = {}
    context = Mock()
    context.__enter__ = Mock(return_value=result)
    context.__exit__ = Mock(return_value=False)
    return context


def private_gate() -> HTTPError:
    return HTTPError(PUBLIC_LOGIN_URL, 302, "redirect", {"Location": GATE}, None)


def deploy(state: str = "ready", **overrides) -> dict:
    return {"id": DEPLOY_ID, "site_id": SITE_ID, "draft": False, "state": state, **overrides}


def published() -> dict:
    return {**SITE, "published_deploy": {"id": DEPLOY_ID, "locked": False}}


class NetlifyReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        dist = root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
        (dist / "_redirects").write_text("/* /index.html 200\n", encoding="utf-8")
        (dist / "_headers").write_text(HEADERS, encoding="utf-8")
        (dist / "assets/app.js").write_text(f'const api = "{PUBLIC_API_ORIGIN}";', encoding="utf-8")
        self.archive = root / "release.zip"
        prepare_archive(dist, self.archive, COMMIT, PUBLIC_API_ORIGIN)
        patcher = patch("socket.socket", side_effect=AssertionError("network access is forbidden in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exact_protected_context_required(self) -> None:
        self.assertEqual(validate_context(CONTEXT), COMMIT)
        for name, value in (
            ("GITHUB_ACTIONS", "false"), ("GITHUB_EVENT_NAME", "pull_request"),
            ("GITHUB_REPOSITORY", "other/repo"), ("GITHUB_REF", "refs/heads/main"),
            ("NETLIFY_RELEASE_APPROVED", "false"), ("GITHUB_SHA", "HEAD"),
        ):
            with self.subTest(name=name), self.assertRaises(ReleaseNotSent) as error:
                validate_context({**CONTEXT, name: value})
            self.assertNotIn(TOKEN, str(error.exception))

    def test_archive_validates_exact_commit_and_rejects_unsafe_names(self) -> None:
        self.assertEqual(read_validated_archive(self.archive, COMMIT), self.archive.read_bytes())
        for name in ("", "/absolute", "../up", "a/../up", "a//b", ".env", "folder/.env", "private.pem", "a\\b", "foo\nbar"):
            with self.subTest(name=name):
                self.assertFalse(_safe_archive_name(name))
        self.assertTrue(_safe_archive_name("assets/app.js"))
        with self.assertRaises(ReleaseNotSent):
            read_validated_archive(self.archive, "f" * 40)
        with self.assertRaises(ReleaseNotSent):
            read_validated_archive(self.archive, "HEAD")
        link = self.archive.parent / "link.zip"
        link.symlink_to(self.archive)
        with self.assertRaises(ReleaseNotSent):
            read_validated_archive(link, COMMIT)

    def test_archive_rejects_tampering_and_extra_sensitive_file(self) -> None:
        original = self.archive.read_bytes()
        self.archive.write_bytes(b"not a zip")
        with self.assertRaises(ReleaseNotSent):
            read_validated_archive(self.archive, COMMIT)
        self.archive.write_bytes(original)
        with ZipFile(self.archive, "a") as archive:
            archive.writestr("secret.pem", "fake secret")
        with self.assertRaises(ReleaseNotSent):
            read_validated_archive(self.archive, COMMIT)

    def test_release_requires_explicit_unlocked_state(self) -> None:
        validate_release_site(SITE)
        invalid = (
            {**SITE, "id": "other"},
            {**SITE, "build_settings": {"stop_builds": False}},
            {**SITE, "prevent_non_git_prod_deploys": True},
            {key: value for key, value in SITE.items() if key != "prevent_non_git_prod_deploys"},
            {**SITE, "published_deploy": None},
            {**SITE, "published_deploy": {"id": "previous_deploy", "locked": True}},
            {**SITE, "published_deploy": {"id": "previous_deploy"}},
            {**SITE, "published_deploy": {"id": "../other", "locked": False}},
        )
        for site in invalid:
            with self.subTest(keyset=sorted(site)), self.assertRaises(ReleaseNotSent):
                validate_release_site(site)

    def test_post_is_fixed_zip_body_and_never_contains_token_in_url(self) -> None:
        payload = read_validated_archive(self.archive, COMMIT)
        request = build_upload_request(TOKEN, COMMIT, payload)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, f"{SITE_API_URL}/deploys?title=github-{COMMIT}")
        self.assertNotIn(TOKEN, request.full_url)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(request.get_header("Content-type"), "application/zip")
        self.assertEqual(request.data, payload)
        with self.assertRaises(ReleaseNotSent):
            build_upload_request(TOKEN, "HEAD", payload)
        with self.assertRaises(ReleaseNotSent):
            build_upload_request("", COMMIT, payload)

    def test_success_sends_one_post_then_checks_ready_and_published(self) -> None:
        opener, sleeper = Mock(), Mock()
        opener.open.side_effect = [
            response(SITE), private_gate(), response(deploy("processing")),
            response(deploy("processing")), response(deploy("ready")), response(published()), private_gate(),
        ]
        release(TOKEN, COMMIT, self.archive, opener, clock=lambda: 0, sleep=sleeper)
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual([item.get_method() for item in requests], ["GET", "GET", "POST", "GET", "GET", "GET", "GET"])
        self.assertEqual(sum(item.get_method() == "POST" for item in requests), 1)
        self.assertEqual(requests[2].data, self.archive.read_bytes())
        for request in requests:
            self.assertNotIn(TOKEN, request.full_url)
            if request.full_url == PUBLIC_LOGIN_URL:
                self.assertIsNone(request.get_header("Authorization"))
        sleeper.assert_called_once_with(5)

    def test_preflight_failure_never_posts(self) -> None:
        opener = Mock()
        opener.open.side_effect = [response(SITE), response(b"public page")]
        with self.assertRaises(ReleaseNotSent):
            release(TOKEN, COMMIT, self.archive, opener)
        self.assertTrue(all(call.args[0].get_method() == "GET" for call in opener.open.call_args_list))
        opener = Mock()
        opener.open.return_value = response({**SITE, "published_deploy": {"id": "old", "locked": True}})
        with self.assertRaises(ReleaseNotSent):
            release(TOKEN, COMMIT, self.archive, opener)
        opener.open.assert_called_once()

    def test_post_errors_are_uncertain_never_retried_or_leaked(self) -> None:
        request = build_upload_request(TOKEN, COMMIT, read_validated_archive(self.archive, COMMIT))
        cases = (
            HTTPError(request.full_url, 401, TOKEN, {"Secret": TOKEN}, io.BytesIO(TOKEN.encode())),
            URLError(TOKEN), TimeoutError(TOKEN),
            response(b"bad json"), response(deploy(site_id="wrong")),
            response(deploy(id="../../other")), response(deploy(draft=True)),
            response(deploy(), status=204),
        )
        for case in cases:
            opener = Mock()
            if isinstance(case, Exception):
                opener.open.side_effect = case
            else:
                opener.open.return_value = case
            with self.subTest(kind=type(case).__name__), self.assertRaises(ReleaseOutcomeUnknown) as error:
                send_upload(request, opener)
            self.assertNotIn(TOKEN, str(error.exception))
            opener.open.assert_called_once()

    def test_ready_without_matching_published_id_is_not_success(self) -> None:
        opener = Mock()
        opener.open.side_effect = [response(deploy()), response(SITE)]
        times = iter([0, 181])
        sleeper = Mock()
        with self.assertRaises(ReleaseOutcomeUnknown):
            wait_for_publication(TOKEN, DEPLOY_ID, opener, clock=lambda: next(times), sleep=sleeper)
        sleeper.assert_not_called()

    def test_failed_unknown_or_wrong_deploy_state_never_succeeds(self) -> None:
        for value in (deploy("error"), deploy("unexpected"), deploy("ready", site_id="other")):
            opener = Mock()
            opener.open.return_value = response(value)
            with self.subTest(value=value), self.assertRaises(ReleaseOutcomeUnknown):
                wait_for_publication(TOKEN, DEPLOY_ID, opener, clock=lambda: 0, sleep=Mock())
            opener.open.assert_called_once()

    def test_privacy_failure_after_publication_is_reported_separately(self) -> None:
        opener = Mock()
        opener.open.side_effect = [
            response(SITE), private_gate(), response(deploy()), response(deploy()), response(published()), response(b"public"),
        ]
        with self.assertRaises(ReleasePublishedPrivacyUnknown):
            release(TOKEN, COMMIT, self.archive, opener, clock=lambda: 0, sleep=Mock())
        self.assertEqual(sum(call.args[0].get_method() == "POST" for call in opener.open.call_args_list), 1)

    def test_cli_without_protected_context_never_opens_network(self) -> None:
        output = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["netlify_release", "--archive", str(self.archive)]),
            patch("tools.netlify_release.make_opener") as opener,
            contextlib.redirect_stderr(output),
        ):
            self.assertEqual(main(), 1)
        opener.assert_not_called()
        self.assertIn("no Netlify deployment was requested", output.getvalue())

    def test_cli_reports_uncertainty_without_printing_sensitive_exception(self) -> None:
        output = io.StringIO()
        with (
            patch.dict(os.environ, CONTEXT, clear=True),
            patch("sys.argv", ["netlify_release", "--archive", str(self.archive)]),
            patch("tools.netlify_release.make_opener", return_value=Mock()),
            patch("tools.netlify_release.release", side_effect=ReleaseOutcomeUnknown(TOKEN)),
            contextlib.redirect_stderr(output),
        ):
            self.assertEqual(main(), 1)
        self.assertIn("may already exist", output.getvalue())
        self.assertNotIn(TOKEN, output.getvalue())


if __name__ == "__main__":
    unittest.main()
