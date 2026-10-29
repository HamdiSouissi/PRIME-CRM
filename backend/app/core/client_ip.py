"""Resolve login client addresses at an explicitly configured trust boundary.

The ASGI server must preserve the socket peer (Uvicorn: --no-proxy-headers).
Forwarded headers are accepted only from a configured, isolated proxy that is
known to replace the chosen single-address header on every request.
"""

from functools import lru_cache
import ipaddress
from typing import Any


class ClientIPError(ValueError):
    """An address or proxy boundary could not be verified."""


def canonical_client_ip(value: object) -> str:
    """Parse one IPv4/IPv6 address, folding IPv4-mapped IPv6 into IPv4."""
    if not isinstance(value, str) or len(value) > 45:
        raise ClientIPError("Invalid client address")
    value = value.strip()
    # Scope identifiers are host-specific, not stable client identities.
    if not value or "%" in value:
        raise ClientIPError("Invalid client address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ClientIPError("Invalid client address") from None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
        raise ClientIPError("Invalid client address")
    return str(address)


@lru_cache(maxsize=32)
def trusted_proxy_networks(value: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    if not value or len(value) > 2048:
        raise ValueError("CLIENT_IP_TRUSTED_PROXIES must contain explicit IP addresses or CIDRs")
    parts = value.split(",")
    if len(parts) > 32 or any(not part.strip() for part in parts):
        raise ValueError("CLIENT_IP_TRUSTED_PROXIES must contain explicit IP addresses or CIDRs")
    networks = []
    for part in parts:
        try:
            network = ipaddress.ip_network(part.strip(), strict=True)
        except ValueError:
            raise ValueError("CLIENT_IP_TRUSTED_PROXIES must contain explicit IP addresses or CIDRs") from None
        if network.prefixlen == 0:
            raise ValueError("A proxy trust range may not include every address")
        networks.append(network)
    return tuple(networks)


def effective_ip_mode(config: Any) -> str:
    mode = config.CLIENT_IP_MODE
    if not mode and config.APP_ENV != "production":
        mode = "direct"
    if mode not in {"direct", "trusted_proxy"}:
        raise ValueError("CLIENT_IP_MODE must explicitly be direct or trusted_proxy in production")
    if mode == "trusted_proxy":
        if config.CLIENT_IP_PROXY_HEADER not in {"cf-connecting-ip", "x-real-ip"}:
            raise ValueError("CLIENT_IP_PROXY_HEADER must select a verified single-address header")
        trusted_proxy_networks(config.CLIENT_IP_TRUSTED_PROXIES)
    elif config.CLIENT_IP_PROXY_HEADER or config.CLIENT_IP_TRUSTED_PROXIES:
        raise ValueError("Proxy header and networks may be set only in trusted_proxy mode")
    return mode


def _socket_peer(scope: dict, config: Any) -> str:
    peer = scope.get("client")
    if not isinstance(peer, (list, tuple)) or len(peer) != 2:
        raise ClientIPError("Socket peer unavailable")
    if config.APP_ENV == "production" and (type(peer[1]) is not int or not 1 <= peer[1] <= 65535):
        # Uvicorn 0.30.6 sets port 0 when its ProxyHeadersMiddleware rewrites
        # scope.client from X-Forwarded-For. Refuse that lossy identity even if
        # the operator accidentally omits --no-proxy-headers. This check is
        # defense in depth, not a replacement for the required server flag.
        raise ClientIPError("Socket peer was rewritten or is unavailable")
    return canonical_client_ip(peer[0])


def is_trusted_proxy_peer(scope: dict, config: Any) -> bool:
    """Recognize only an explicitly configured immediate proxy socket peer."""
    try:
        if effective_ip_mode(config) != "trusted_proxy":
            return False
        peer_address = ipaddress.ip_address(_socket_peer(scope, config))
        return any(peer_address in network for network in trusted_proxy_networks(config.CLIENT_IP_TRUSTED_PROXIES))
    except (TypeError, ValueError):
        return False


def resolve_client_ip(scope: dict, config: Any) -> str:
    """Return a canonical IP, or refuse requests with an unproven identity.

    Never parse X-Forwarded-For or fall back to a caller-supplied header.
    Network allowlists identify the immediate proxy, not the original client;
    their operator must independently ensure that only sanitizing proxies can
    connect from those networks.
    """
    try:
        mode = effective_ip_mode(config)
        peer_ip = _socket_peer(scope, config)
        peer_address = ipaddress.ip_address(peer_ip)
        if mode == "direct":
            # A public deployment behind a private proxy must not silently
            # collapse all clients into one shared proxy-IP bucket.
            if config.APP_ENV == "production" and not peer_address.is_global:
                raise ClientIPError("Direct client address is not public")
            return peer_ip

        if not is_trusted_proxy_peer(scope, config):
            raise ClientIPError("Untrusted proxy peer")
        name = config.CLIENT_IP_PROXY_HEADER.encode("ascii")
        values = [value for header, value in scope.get("headers", []) if header.lower() == name]
        if len(values) != 1:
            raise ClientIPError("Missing or duplicate client address header")
        try:
            value = values[0].decode("ascii")
        except (AttributeError, UnicodeDecodeError):
            raise ClientIPError("Invalid client address header") from None
        client_ip = canonical_client_ip(value)
        if config.APP_ENV == "production" and not ipaddress.ip_address(client_ip).is_global:
            raise ClientIPError("Forwarded client address is not public")
        return client_ip
    except (TypeError, ValueError):
        # Never disclose network configuration, addresses, or supplied headers.
        raise ClientIPError("Client address unavailable") from None
