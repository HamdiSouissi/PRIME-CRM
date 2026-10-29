"""Read-only Netlify release checks; no deployment or configuration writes.

The caller must explicitly approve access to the protected GitHub environment.
The personal access token is read from an environment variable and is never
printed, embedded in a URL, or forwarded to the public site. All URLs and the
project identity are fixed here. Network failures are reported without their
potentially sensitive details.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

SITE_ID = "6885b960-ddd4-4ebe-a278-6d9b8ebaf5a4"
SITE_NAME = "transcendent-phoenix-64e598"
SITE_HOST = f"{SITE_NAME}.netlify.app"
SITE_API_URL = f"https://api.netlify.com/api/v1/sites/{SITE_ID}"
PUBLIC_LOGIN_URL = f"https://{SITE_HOST}/login"
_TIMEOUT_SECONDS = 20
_MAX_RESPONSE_BYTES = 1_048_576
_MAX_PRIVACY_BODY_BYTES = 65_536
_PROBE_USER_AGENT = "prime-crm-read-only-preflight"
# OAuth bearer-token characters, with no whitespace, control characters or URL.
_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]{8,510}={0,2}\Z", re.ASCII)
# Netlify currently serves a 401 HTML page whose inline JavaScript navigates to
# edge-access. Do not execute it: recognize only this exact, bounded template
# and validate its embedded URL. A template change fails closed for review.
_NETLIFY_LOGIN_SCRIPT = re.compile(
    r"""\s*window\.onload\s*=\s*function\s*\(\s*\)\s*\{\s*
    var\s+fragment\s*=\s*window\.location\.hash\s*;\s*
    var\s+url\s*=\s*new\s+URL\s*\(\s*
    (?P<quote>['"])(?P<target>[A-Za-z0-9._~:/?%=&+\\-]+)(?P=quote)\s*\)\s*;\s*
    if\s*\(\s*fragment\s*\)\s*\{\s*
    var\s+requestedPath\s*=\s*url\.searchParams\.get\s*\(\s*
    (?P<q1>['"])requested_path(?P=q1)\s*\)\s*;\s*
    url\.searchParams\.set\s*\(\s*(?P<q2>['"])requested_path(?P=q2)\s*,\s*
    requestedPath\s*\+\s*fragment\s*\)\s*;\s*\}\s*
    window\.location\.href\s*=\s*url\.toString\s*\(\s*\)\s*;\s*\}\s*;\s*""",
    re.ASCII | re.VERBOSE,
)


class PreflightError(ValueError):
    """A sanitized preflight failure that contains no token or response body."""


class NoRedirect(HTTPRedirectHandler):
    """Do not forward a bearer token or follow an unexpected redirect."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def make_opener():
    """Use verified HTTPS, no inherited proxy, no redirects, and no key logging."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    return build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))


def validate_token(token: str) -> None:
    if not _TOKEN.fullmatch(token):
        raise PreflightError("Missing or invalid Netlify token")


def get_site(token: str, opener) -> dict:
    """GET one predetermined project; never display its potentially sensitive body."""
    validate_token(token)
    request = Request(
        SITE_API_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "prime-crm-read-only-preflight",
        },
    )
    try:
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.getcode() != 200:
                raise PreflightError("Netlify project lookup failed")
            body = response.read(_MAX_RESPONSE_BYTES + 1)
    except PreflightError:
        raise
    except HTTPError as error:
        # Never echo headers, response bodies, URLs, or exception details.
        raise PreflightError(f"Netlify project lookup failed (HTTP {error.code})") from None
    except Exception:
        raise PreflightError("Netlify project lookup failed or timed out") from None
    if not isinstance(body, bytes) or len(body) > _MAX_RESPONSE_BYTES:
        raise PreflightError("Netlify project response was invalid")
    try:
        site = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise PreflightError("Netlify project response was invalid") from None
    if not isinstance(site, dict):
        raise PreflightError("Netlify project response was invalid")
    return site


def validate_site(site: dict) -> None:
    """Require the expected project and a stopped Git build configuration."""
    if site.get("id") != SITE_ID or site.get("name") != SITE_NAME:
        raise PreflightError("Netlify returned a different project")
    settings = site.get("build_settings")
    if not isinstance(settings, dict) or settings.get("stop_builds") is not True:
        raise PreflightError("Netlify stopped-builds setting was not confirmed")
    if site.get("prevent_non_git_prod_deploys") is True:
        raise PreflightError("Netlify currently prevents non-Git production deployments")
    published = site.get("published_deploy")
    if isinstance(published, dict) and published.get("locked") is True:
        raise PreflightError("The published Netlify deployment is locked")


def is_private_redirect(location: str) -> bool:
    """Check Netlify's unauthenticated edge-access redirect for this project."""
    try:
        parts = urlsplit(location)
        if (
            parts.scheme != "https"
            or parts.netloc != "app.netlify.com"
            or parts.path != "/edge-access"
            or parts.fragment
        ):
            return False
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    return (
        query.get("domain") == [SITE_HOST]
        and query.get("site_id") == [SITE_ID]
        and query.get("requested_path") == ["/login"]
    )


class _LoginChallengeParser(HTMLParser):
    """Collect only inline scripts and title text, without executing content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[str] = []
        self.scripts: list[str] = []
        self._title: list[str] | None = None
        self._script: list[str] | None = None
        self.invalid = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "title":
            if self._title is not None:
                self.invalid = True
            self._title = []
        elif tag == "script":
            if self._script is not None or any(name == "src" for name, _value in attrs):
                self.invalid = True
            self._script = []

    def handle_data(self, data) -> None:
        if self._title is not None:
            self._title.append(data)
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag) -> None:
        if tag == "title" and self._title is not None:
            self.titles.append("".join(self._title))
            self._title = None
        elif tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None


def is_private_login_html(body: bytes) -> bool:
    """Recognize Netlify's 401 challenge for this project without running JS.

    This is a point-in-time observation, not proof of privacy for all routes or
    future requests. Unknown HTML, encodings and script templates fail closed.
    """
    if not isinstance(body, bytes) or not body or len(body) > _MAX_PRIVACY_BODY_BYTES:
        return False
    try:
        parser = _LoginChallengeParser()
        parser.feed(body.decode("utf-8", errors="strict"))
        parser.close()
    except (UnicodeDecodeError, ValueError):
        return False
    if (
        parser.invalid
        or parser._title is not None
        or parser._script is not None
        or len(parser.titles) != 1
        or parser.titles[0].strip() != "Login Redirect"
        or len(parser.scripts) != 1
    ):
        return False
    match = _NETLIFY_LOGIN_SCRIPT.fullmatch(parser.scripts[0])
    if match is None:
        return False
    # Only the two known JS escapes are accepted; do not interpret arbitrary JS.
    target = match.group("target").replace(r"\/", "/").replace(r"\u0026", "&")
    return "\\" not in target and is_private_redirect(target)


def get_private_login_response(opener, *, user_agent: str = _PROBE_USER_AGENT) -> tuple[int, str, bytes]:
    """Get /login without credentials, redirects, response logging, or retries."""
    request = Request(
        PUBLIC_LOGIN_URL,
        method="GET",
        headers={"Accept": "text/html", "Cache-Control": "no-cache", "User-Agent": user_agent},
    )
    try:
        try:
            response = opener.open(request, timeout=_TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        with response:
            status = response.getcode()
            location = response.headers.get("Location", "") if response.headers is not None else ""
            # Only an unauthorized page is inspected, and never recorded or printed.
            body = response.read(_MAX_PRIVACY_BODY_BYTES + 1) if status == 401 else b""
    except Exception:
        raise PreflightError("The Netlify privacy probe failed or timed out") from None
    if (
        type(status) is not int
        or not 100 <= status <= 599
        or not isinstance(location, str)
        or not isinstance(body, bytes)
        or len(body) > _MAX_PRIVACY_BODY_BYTES
    ):
        raise PreflightError("The Netlify privacy probe returned an invalid response")
    return status, location, body


def check_private_login(opener) -> None:
    """Require a recognized Netlify challenge; unknown responses fail closed."""
    status, location, body = get_private_login_response(opener)
    if status in (301, 302, 303, 307, 308) and is_private_redirect(location):
        return
    if status == 401 and is_private_login_html(body):
        return
    raise PreflightError("The Netlify private login challenge was not confirmed")


def run_preflight(token: str, opener) -> None:
    validate_token(token)
    validate_site(get_site(token, opener))
    check_private_login(opener)


def main() -> int:
    token = os.environ.get("NETLIFY_AUTH_TOKEN", "")
    try:
        validate_token(token)
        opener = make_opener()
        run_preflight(token, opener)
    except PreflightError as error:
        print(f"::error::{error}; no deployment or configuration change was requested.", file=sys.stderr)
        return 1
    except Exception:
        # Do not echo unexpected exceptions: they may contain sensitive data.
        print("::error::Netlify preflight failed; no deployment or configuration change was requested.", file=sys.stderr)
        return 1
    print("Read-only checks passed for the expected Netlify project and stopped builds.")
    print("The anonymous /login probe recognized a Netlify private-access challenge for the project.")
    print("This is a point-in-time observation, not proof of privacy for every route or future request.")
    print("No deployment or configuration change was requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
