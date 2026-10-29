"""Validate the operator-specified external HTTPS origin, never request headers."""

from dataclasses import dataclass
from functools import lru_cache
import ipaddress
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PublicOrigin:
    authority: str
    host: str
    port: int


@lru_cache(maxsize=32)
def public_https_origin(value: str) -> PublicOrigin:
    """Parse one explicit HTTPS origin suitable for server-generated redirects.

    The operator must independently ensure that the public ingress enforces
    HTTPS and that this is the actual service origin. This parser does not
    authenticate a proxy, client address, Host header, or request transport.
    """
    def invalid():
        raise ValueError("PUBLIC_API_ORIGIN must be one exact HTTPS origin with a valid hostname")

    if (
        not value or len(value) > 300 or not value.isascii()
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
        or any(char in value for char in "\\?#")
    ):
        invalid()
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)
        ):
            invalid()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if len(host) > 253 or len(labels) < 2 or labels[-1].isdigit() or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ):
                invalid()
            authority = host
        else:
            if not address.is_global or getattr(address, "scope_id", None):
                invalid()
            authority = f"[{address}]" if address.version == 6 else str(address)
        if port is not None:
            authority += f":{port}"
        # Reject ambiguous ports, invalid brackets, userinfo, and alternate
        # representations rather than forwarding an unchecked Host header.
        if parsed.netloc.lower() != authority:
            invalid()
        return PublicOrigin(authority=authority, host=host, port=port or 443)
    except ValueError:
        invalid()
