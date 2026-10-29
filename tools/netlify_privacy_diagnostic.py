"""Anonymous, sanitized diagnostic for the Netlify /login privacy probe.

This is not a release or a privacy guarantee. It sends one fixed GET with no
credentials and does not follow redirects. Only a status and comparison flags
are printed; never print the Location, response body, headers, or exceptions.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from tools.netlify_preflight import (
    SITE_HOST,
    SITE_ID,
    get_private_login_response,
    is_private_redirect,
    make_opener,
)


def describe_response(status: int, location: str) -> str:
    """Report only a numeric status and whether fixed comparisons matched."""
    if type(status) is not int or not 100 <= status <= 599 or not isinstance(location, str):
        return "invalid-response"
    flags = {
        "location": bool(location),
        "https": False,
        "host": False,
        "path": False,
        "fragment": False,
        "query": False,
        "domain": False,
        "site": False,
        "login": False,
        "match": False,
    }
    try:
        parts = urlsplit(location)
        flags["https"] = parts.scheme == "https"
        flags["host"] = parts.netloc == "app.netlify.com"
        flags["path"] = parts.path == "/edge-access"
        flags["fragment"] = not parts.fragment
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
        flags["query"] = True
        flags["domain"] = query.get("domain") == [SITE_HOST]
        flags["site"] = query.get("site_id") == [SITE_ID]
        flags["login"] = query.get("requested_path") == ["/login"]
        flags["match"] = status in (301, 302, 303, 307, 308) and is_private_redirect(location)
    except ValueError:
        pass
    comparisons = ";".join(f"{name}:{int(value)}" for name, value in flags.items())
    return f"HTTP:{status};{comparisons}"


def main() -> int:
    try:
        status, location = get_private_login_response(make_opener())
        observation = describe_response(status, location)
    except Exception:
        # The exception can contain response or network details. Do not echo it.
        observation = "probe-error"
    # The caller may capture this as a GitHub Actions output. It contains only
    # literal names, integers and boolean flags, never response text or a URL.
    print(f"observation={observation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
