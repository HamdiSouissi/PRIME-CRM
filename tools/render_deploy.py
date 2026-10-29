"""Request a Render deploy of one tested commit; never print the hook.

Run only after the CI jobs, production approval and migration-fingerprint
check. An accepted request is NOT confirmation that the deployment is live.
A request is sent at most once; on an uncertain outcome inspect Render before
retrying to avoid duplicate deploys.
"""

from __future__ import annotations

import os
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from tools.render_hook_check import InvalidHook, validate_hook

_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_TIMEOUT_SECONDS = 20


class InvalidRelease(ValueError):
    """The deploy hook or commit is absent or malformed."""


class NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect when a bearer credential is in the URL."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def build_request(hook: str, commit: str) -> Request:
    """Create, but do not send, a POST to Render pinned to a full Git SHA."""
    try:
        validate_hook(hook)
    except InvalidHook:
        raise InvalidRelease("Missing or invalid Render hook") from None
    if not _COMMIT.fullmatch(commit):
        raise InvalidRelease("Missing or invalid commit SHA")
    parts = urlsplit(hook)
    target = urlunsplit((parts.scheme, parts.netloc, parts.path, f"{parts.query}&ref={commit}", ""))
    return Request(target, method="POST", headers={"User-Agent": "prime-crm-github-release"})


def request_deploy(request: Request, opener) -> int:
    """Send exactly once; return only a sanitized result code."""
    try:
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            status = response.getcode()
    except HTTPError as error:
        # Do not log error.url, headers, response bodies, or exception text.
        print(f"::error::Render rejected the request (HTTP {error.code}). Check Render before retrying.", file=sys.stderr)
        return 1
    except Exception:
        # A timeout or unexpected failure can occur after Render received the
        # request. Suppress exception details because they can contain the URL.
        print("::error::Deploy request outcome is unknown. Check Render before retrying.", file=sys.stderr)
        return 1

    if status == 200:
        print("Render accepted the deployment request. Verify the commit and Live status in Render.")
        return 0
    if status == 202:
        print("Render queued the deployment request. Verify the commit and Live status in Render.")
        return 0
    print("::error::Unexpected response; check Render before retrying.", file=sys.stderr)
    return 1


def main() -> int:
    try:
        request = build_request(os.environ.get("RENDER_DEPLOY_HOOK_URL", ""), os.environ.get("GITHUB_SHA", ""))
    except InvalidRelease as error:
        # InvalidRelease messages never include any supplied values.
        print(f"::error::{error}; no request was sent.", file=sys.stderr)
        return 1

    # No automatic redirects, proxy inherited from the environment, or retries.
    # urllib uses the platform's default TLS certificate and hostname validation.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    return request_deploy(request, opener)


if __name__ == "__main__":
    raise SystemExit(main())
