"""Prepare one approved Netlify frontend release, with bounded verification.

Its tests use fictitious data. Creating a deploy must only happen after CI, a
protected human approval, backend compatibility and migration checks, and a
separate decision to publish. A POST may already have created or published a
deploy even if a response is missing: never retry without inspecting Netlify.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import sys
import time
from pathlib import Path, PurePosixPath
from urllib.request import Request
from zipfile import BadZipFile, ZipFile

from tools.frontend_release import (
    _FORBIDDEN_SUFFIXES,
    _MAX_FILES,
    _MAX_TOTAL_BYTES,
    PUBLIC_API_ORIGIN,
    InvalidFrontendBuild,
    validate_files,
)
from tools.netlify_preflight import (
    SITE_API_URL,
    SITE_ID,
    SITE_NAME,
    PreflightError,
    check_private_login,
    get_site,
    make_opener,
    validate_site,
    validate_token,
)

_REPOSITORY = "HamdiSouissi/PRIME-CRM"
_REF = "refs/heads/arena/a18b007f-prime-crm"
_GITHUB_BRANCH_URL = "https://api.github.com/repos/HamdiSouissi/PRIME-CRM/git/ref/heads/arena/a18b007f-prime-crm"
_COMMIT = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_GITHUB_TOKEN = re.compile(r"[A-Za-z0-9_.-]{8,1024}\Z", re.ASCII)
_DEPLOY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z", re.ASCII)
_MAX_ARCHIVE_BYTES = _MAX_TOTAL_BYTES + 1_048_576
_MAX_JSON_BYTES = 1_048_576
_GET_TIMEOUT_SECONDS = 20
_POST_TIMEOUT_SECONDS = 45
_POLL_SECONDS = 5
_POLL_LIMIT_SECONDS = 180
_WAIT_STATES = {
    "new", "pending_review", "accepted", "enqueued", "building", "uploading", "uploaded",
    "preparing", "prepared", "processing", "processed", "retrying",
}
_FAILURE_STATES = {"error", "failed", "canceled", "cancelled", "rejected"}


class ReleaseNotSent(ValueError):
    """A sanitized error before any deployment request was sent."""


class ReleaseOutcomeUnknown(ValueError):
    """A sanitized error after a POST attempt; inspect Netlify before retrying."""


class ReleasePublishedPrivacyUnknown(ReleaseOutcomeUnknown):
    """The deploy is published, but its anonymous privacy check did not pass."""


def validate_context(environment: dict[str, str]) -> str:
    """Require the exact GitHub context and an explicit workflow authorization."""
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_EVENT_NAME") != "push"
        or environment.get("GITHUB_REPOSITORY") != _REPOSITORY
        or environment.get("GITHUB_REF") != _REF
        or environment.get("NETLIFY_RELEASE_APPROVED") != "true"
    ):
        raise ReleaseNotSent("The protected GitHub release context is missing or invalid")
    commit = environment.get("GITHUB_SHA", "")
    if not _COMMIT.fullmatch(commit):
        raise ReleaseNotSent("The tested commit SHA is missing or invalid")
    return commit


def _safe_archive_name(name: str) -> bool:
    if not name or name.startswith("/") or "\\" in name or len(name) > 4096:
        return False
    components = name.split("/")
    if any(not part or part in {".", ".."} or part.startswith(".") for part in components):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        return False
    return PurePosixPath(name).suffix.lower() not in _FORBIDDEN_SUFFIXES


def read_validated_archive(path: Path, commit: str) -> bytes:
    """Revalidate a local ZIP and return exactly the bytes that may be sent."""
    if not _COMMIT.fullmatch(commit) or path.suffix.lower() != ".zip" or path.is_symlink():
        raise ReleaseNotSent("The local archive or tested commit is invalid")
    try:
        # Refuse a symlink even if it changes between the path check and open.
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ReleaseNotSent("The local archive is not a regular file")
            payload = source.read(_MAX_ARCHIVE_BYTES + 1)
        if not payload or len(payload) > _MAX_ARCHIVE_BYTES:
            raise ReleaseNotSent("The local archive has an invalid size")

        files: dict[str, bytes] = {}
        total = 0
        with ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > _MAX_FILES + 1:
                raise ReleaseNotSent("The local archive has an invalid file count")
            for entry in entries:
                name = entry.filename
                mode = entry.external_attr >> 16
                if (
                    not _safe_archive_name(name)
                    or name in files
                    or entry.is_dir()
                    or not stat.S_ISREG(mode)
                    or entry.flag_bits & 1
                    or entry.file_size < 0
                ):
                    raise ReleaseNotSent("The local archive contains an unsafe entry")
                total += entry.file_size
                if total > _MAX_TOTAL_BYTES + 1024:
                    raise ReleaseNotSent("The local archive exceeds its uncompressed size limit")
                files[name] = archive.read(entry)
        expected_info = (json.dumps({"commit": commit}, separators=(",", ":")) + "\n").encode("ascii")
        if files.pop("build-info.json", None) != expected_info:
            raise ReleaseNotSent("The archive does not identify the tested commit")
        validate_files(files, PUBLIC_API_ORIGIN)
    except ReleaseNotSent:
        raise
    except (OSError, ValueError, RuntimeError, EOFError, BadZipFile, InvalidFrontendBuild):
        raise ReleaseNotSent("The local archive could not be validated") from None
    return payload


def validate_release_site(site: dict) -> None:
    """Require explicit evidence that the existing production deploy is unlocked."""
    try:
        validate_site(site)
    except PreflightError:
        raise ReleaseNotSent("The Netlify project checks did not pass") from None
    published = site.get("published_deploy")
    if (
        site.get("prevent_non_git_prod_deploys") is not False
        or not isinstance(published, dict)
        or published.get("locked") is not False
        or not isinstance(published.get("id"), str)
        or not _DEPLOY_ID.fullmatch(published["id"])
    ):
        raise ReleaseNotSent("An unlocked production deployment was not confirmed")


def build_upload_request(token: str, commit: str, payload: bytes) -> Request:
    """Create a POST to the fixed project, with no token in the URL."""
    try:
        validate_token(token)
    except PreflightError:
        raise ReleaseNotSent("The Netlify token is missing or invalid") from None
    if not _COMMIT.fullmatch(commit) or not isinstance(payload, bytes) or not payload:
        raise ReleaseNotSent("The release inputs are invalid")
    return Request(
        f"{SITE_API_URL}/deploys?title=github-{commit}",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/zip",
            "Accept": "application/json",
            "User-Agent": "prime-crm-github-release",
        },
    )


def _read_json_response(response) -> dict:
    body = response.read(_MAX_JSON_BYTES + 1)
    if not isinstance(body, bytes) or len(body) > _MAX_JSON_BYTES:
        raise ValueError("invalid response")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise TypeError("invalid response")
    return value


def validate_github_token(token: str) -> None:
    """Reject absent or unsafe GitHub bearer tokens without echoing them."""
    if not _GITHUB_TOKEN.fullmatch(token):
        raise ReleaseNotSent("The read-only GitHub token is missing or invalid")


def verify_branch_head(token: str, commit: str, opener) -> None:
    """Check the fixed branch immediately before the Netlify POST.

    This limits stale releases but cannot eliminate a concurrent push occurring
    after the check. The GitHub token is never included in a Netlify request.
    """
    validate_github_token(token)
    if not _COMMIT.fullmatch(commit):
        raise ReleaseNotSent("The tested commit SHA is invalid")
    request = Request(
        _GITHUB_BRANCH_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "prime-crm-github-release",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener.open(request, timeout=_GET_TIMEOUT_SECONDS) as response:
            if response.getcode() != 200:
                raise ValueError("unexpected GitHub response")
            ref = _read_json_response(response)
        obj = ref.get("object")
        if ref.get("ref") != _REF or not isinstance(obj, dict) or obj.get("type") != "commit" or obj.get("sha") != commit:
            raise ValueError("branch changed")
    except Exception:  # noqa: BLE001 - prevent remote details and tokens entering logs
        raise ReleaseNotSent("The approved commit is not the current branch head") from None


def send_upload(request: Request, opener) -> str:
    """Send exactly one POST. Do not retry, including on errors or timeouts."""
    try:
        with opener.open(request, timeout=_POST_TIMEOUT_SECONDS) as response:
            if response.getcode() not in (200, 201, 202):
                raise ValueError("unexpected response")
            deploy = _read_json_response(response)
        deploy_id = deploy.get("id")
        if (
            not isinstance(deploy_id, str)
            or not _DEPLOY_ID.fullmatch(deploy_id)
            or deploy.get("site_id") != SITE_ID
            or deploy.get("draft") is True
        ):
            raise ValueError("unconfirmed deploy")
        return deploy_id
    except Exception:  # noqa: BLE001 - keep remote errors and secrets out of logs
        # No exception text, URL, response body, header or token in public logs.
        raise ReleaseOutcomeUnknown("Netlify did not confirm the deployment request") from None


def get_deploy(token: str, deploy_id: str, opener) -> dict:
    """Read only the validated deploy ID within the fixed Netlify project."""
    if not _DEPLOY_ID.fullmatch(deploy_id):
        raise ReleaseOutcomeUnknown("The Netlify deployment identifier is invalid")
    request = Request(
        f"{SITE_API_URL}/deploys/{deploy_id}",
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "prime-crm-github-release"},
    )
    try:
        with opener.open(request, timeout=_GET_TIMEOUT_SECONDS) as response:
            if response.getcode() != 200:
                raise ValueError("unexpected response")
            deploy = _read_json_response(response)
        if deploy.get("id") != deploy_id or deploy.get("site_id") != SITE_ID or deploy.get("draft") is True:
            raise ValueError("wrong deployment")
        return deploy
    except Exception:  # noqa: BLE001 - keep remote errors and secrets out of logs
        raise ReleaseOutcomeUnknown("Netlify deployment status could not be verified") from None


def wait_for_publication(token: str, deploy_id: str, opener, *, clock=time.monotonic, sleep=time.sleep) -> None:
    """Check ready AND that the current published deploy is the requested ID."""
    deadline = clock() + _POLL_LIMIT_SECONDS
    while True:
        deploy = get_deploy(token, deploy_id, opener)
        state = deploy.get("state")
        if state in _FAILURE_STATES:
            raise ReleaseOutcomeUnknown("Netlify reported that the deployment did not complete")
        if state == "ready":
            try:
                site = get_site(token, opener)
            except PreflightError:
                raise ReleaseOutcomeUnknown("The published Netlify deployment could not be verified") from None
            if site.get("id") != SITE_ID or site.get("name") != SITE_NAME:
                raise ReleaseOutcomeUnknown("Netlify returned an unexpected project after the request")
            published = site.get("published_deploy")
            if isinstance(published, dict) and published.get("id") == deploy_id:
                return
        elif state not in _WAIT_STATES:
            raise ReleaseOutcomeUnknown("Netlify returned an unrecognized deployment state")
        if clock() >= deadline:
            raise ReleaseOutcomeUnknown("Netlify did not confirm publication before the timeout")
        sleep(_POLL_SECONDS)


def release(token: str, commit: str, archive: Path, opener, *, github_token: str, clock=time.monotonic, sleep=time.sleep) -> None:
    """Check locally and remotely before one POST; never retry the POST."""
    validate_github_token(github_token)
    payload = read_validated_archive(archive, commit)
    request = build_upload_request(token, commit, payload)
    try:
        validate_release_site(get_site(token, opener))
        check_private_login(opener)
        verify_branch_head(github_token, commit, opener)
    except ReleaseNotSent:
        raise
    except Exception:  # noqa: BLE001 - keep remote errors and secrets out of logs
        raise ReleaseNotSent("The Netlify read-only preflight did not pass") from None

    # From this point forward, an exception cannot prove that nothing changed.
    try:
        deploy_id = send_upload(request, opener)
        wait_for_publication(token, deploy_id, opener, clock=clock, sleep=sleep)
        try:
            check_private_login(opener)
        except Exception:  # noqa: BLE001 - keep remote errors and secrets out of logs
            raise ReleasePublishedPrivacyUnknown("Publication was confirmed, but the private-login probe failed") from None
    except ReleaseOutcomeUnknown:
        raise
    except Exception:  # noqa: BLE001 - keep remote errors and secrets out of logs
        raise ReleaseOutcomeUnknown("The deployment outcome could not be verified") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one approved static frontend release")
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    try:
        commit = validate_context(os.environ)
        token = os.environ.get("NETLIFY_AUTH_TOKEN", "")
        github_token = os.environ.get("GH_READ_TOKEN", "")
        validate_github_token(github_token)
        # Validate the local file before constructing an opener or contacting Netlify.
        read_validated_archive(args.archive, commit)
        opener = make_opener()
        release(token, commit, args.archive, opener, github_token=github_token)
    except ReleasePublishedPrivacyUnknown:
        print("::error::The deploy is published but its privacy probe failed. Check Netlify immediately; do not retry automatically.", file=sys.stderr)
        return 1
    except ReleaseOutcomeUnknown:
        print("::error::A deploy may already exist. Check Netlify before retrying; no automatic retry was made.", file=sys.stderr)
        return 1
    except ReleaseNotSent as error:
        # Whitelist fixed explanations rather than echoing arbitrary exceptions.
        hints = {
            "An unlocked production deployment was not confirmed": "Netlify publishing flags are missing or not explicitly unlocked",
            "The Netlify project checks did not pass": "Netlify project, stopped-builds or publishing checks did not pass",
            "The Netlify read-only preflight did not pass": "Netlify project lookup or anonymous privacy probe did not pass",
            "The approved commit is not the current branch head": "The approved GitHub branch head could not be confirmed",
            "The read-only GitHub token is missing or invalid": "The GitHub read token is missing or invalid",
        }
        hint = hints.get(str(error), "Release validation failed")
        print(f"::error::{hint}; no Netlify deployment was requested.", file=sys.stderr)
        return 1
    except PreflightError:
        print("::error::Release validation failed; no Netlify deployment was requested.", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - keep remote errors and secrets out of logs
        # Unexpected exceptions can contain secrets; the operation may be uncertain.
        print("::error::Release outcome is uncertain. Check Netlify before retrying.", file=sys.stderr)
        return 1
    print("Netlify reports the requested deploy ready and published for the expected project.")
    print("The anonymous private-login probe passed; this does not guarantee privacy of every route or future requests.")
    print("Verify the site and CRM login manually. No automatic retry was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
