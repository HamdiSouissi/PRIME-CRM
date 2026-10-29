"""Strict, fail-closed policy for AI provider origins.

An operator must explicitly allow each public HTTPS origin. The separate local
Ollama exception is available only in development and only when opted in.
Network addresses are checked separately immediately before each request.
"""

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from ...config import settings


DEFAULT_OPENAI_BASE_URL = "https://www.codecraftapi.com/v1"
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
URL_ERROR = "URL du fournisseur IA invalide : utilisez une origine autorisée sans identifiants, paramètres ou fragment."
POLICY_ERROR = "Destination IA non autorisée : vérifiez AI_ALLOWED_ORIGINS et la configuration locale."

_DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class AIProviderURLError(ValueError):
    """A fixed error that never includes a URL, address or credential."""


@dataclass(frozen=True)
class ProviderTarget:
    base_url: str
    scheme: str
    hostname: str
    port: int
    local_ollama: bool

    @property
    def host_header(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        return self.hostname if self.port == default_port else f"{self.hostname}:{self.port}"


def _is_domain(hostname: str) -> bool:
    if not hostname.isascii() or len(hostname) > 253 or hostname.endswith("."):
        return False
    labels = hostname.split(".")
    if len(labels) < 2 or any(_DOMAIN_LABEL.fullmatch(label) is None for label in labels):
        return False
    # Do not accept numeric or alternative textual IP literals as DNS names.
    if not any("a" <= char <= "z" for char in labels[-1]):
        return False
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        return True


def _split_url(value: str):
    try:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 255
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or any(char in value for char in ("\\", "?", "#"))
        ):
            raise ValueError
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or not host.isascii()
            or parsed.username is not None
            or parsed.password is not None
            or "@" in parsed.netloc
            or "%" in parsed.netloc
            or "[" in parsed.netloc  # IPv6 destinations are not supported.
            or "]" in parsed.netloc
            or (parsed.path and not parsed.path.startswith("/"))
        ):
            raise ValueError
        if ":" in parsed.netloc:
            _, port_text = parsed.netloc.rsplit(":", 1)
            if not port_text.isascii() or not port_text.isdigit() or not port or port > 65535:
                raise ValueError
        hostname = host.lower()
        return parsed, hostname, port or (443 if parsed.scheme == "https" else 80)
    except (TypeError, ValueError):
        raise AIProviderURLError(URL_ERROR) from None


def parse_allowed_origins(value: str) -> frozenset[str]:
    """Parse exact HTTPS origins only; no wildcards, IPs, paths or secrets."""
    if not isinstance(value, str):
        raise AIProviderURLError(POLICY_ERROR)
    if not value.strip():
        return frozenset()
    entries = value.split(",")
    if len(entries) > 50 or any(not entry.strip() for entry in entries):
        raise AIProviderURLError(POLICY_ERROR)
    result = set()
    for entry in entries:
        parsed, hostname, port = _split_url(entry.strip())
        if parsed.scheme != "https" or parsed.path not in {"", "/"} or not _is_domain(hostname):
            raise AIProviderURLError(POLICY_ERROR)
        result.add(f"https://{hostname}" + (f":{port}" if port != 443 else ""))
    return frozenset(result)


def provider_target(value: str | None, *, ollama: bool) -> ProviderTarget:
    url = value or (DEFAULT_OLLAMA_BASE_URL if ollama else DEFAULT_OPENAI_BASE_URL)
    parsed, hostname, port = _split_url(url)
    local = (
        ollama
        and settings.APP_ENV == "development"
        and settings.AI_ALLOW_LOCAL_OLLAMA
        and parsed.scheme == "http"
        and hostname in {"127.0.0.1", "localhost", "host.docker.internal"}
        and port == 11434
        and parsed.path in {"", "/"}
    )
    if not local:
        if parsed.scheme != "https" or not _is_domain(hostname):
            raise AIProviderURLError(URL_ERROR)
        origin = f"https://{hostname}" + (f":{port}" if port != 443 else "")
        if origin not in parse_allowed_origins(settings.AI_ALLOWED_ORIGINS):
            raise AIProviderURLError(POLICY_ERROR)
    netloc = hostname + (f":{port}" if port != (443 if parsed.scheme == "https" else 80) else "")
    canonical = urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
    return ProviderTarget(canonical, parsed.scheme, hostname, port, local)


def validate_openai_base_url(value: str | None) -> str:
    return provider_target(value, ollama=False).base_url


def validate_ollama_base_url(value: str | None) -> str:
    return provider_target(value, ollama=True).base_url


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
