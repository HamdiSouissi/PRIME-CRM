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
    """Require the expected redirect; an unrecognized response fails closed."""
    status, location, _body = get_private_login_response(opener)
    if status not in (301, 302, 303, 307, 308) or not is_private_redirect(location):
        raise PreflightError("The Netlify private login redirect was not confirmed")


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
    print("The anonymous /login probe reached Netlify's private-access redirect.")
    print("No deployment or configuration change was requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
