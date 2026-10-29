"""Basic transport and credential-in-URL checks for AI provider requests.

This does not provide complete SSRF protection: DNS, network destinations,
Ollama URLs and provider access still need a separate security review.
"""

from urllib.parse import urlsplit

from ...config import settings


DEFAULT_OPENAI_BASE_URL = "https://www.codecraftapi.com/v1"
URL_ERROR = "URL du fournisseur IA invalide : utilisez une URL sans identifiants ni paramètres ; HTTPS est requis en production."


class AIProviderURLError(ValueError):
    """An invalid provider URL, without echoing its contents."""


def validate_openai_base_url(value: str | None) -> str:
    url = value or DEFAULT_OPENAI_BASE_URL
    try:
        parsed = urlsplit(url)
        port = parsed.port  # Also rejects malformed/out-of-range ports.
        valid = (
            parsed.scheme in {"http", "https"}
            and (settings.APP_ENV != "production" or parsed.scheme == "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and (port is None or 0 < port <= 65535)
            and "?" not in url
            and "#" not in url
            and not any(char.isspace() or ord(char) < 32 for char in url)
            and "\\" not in url
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise AIProviderURLError(URL_ERROR)
    return url.rstrip("/")


def response_url(value: str | None) -> str | None:
    """Avoid returning credentials from unsafe URLs saved by older versions."""
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            return None
    except ValueError:
        return None
    return value
