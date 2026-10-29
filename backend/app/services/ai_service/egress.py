"""Single guarded egress path for every AI HTTP request.

Public destinations require an operator-approved HTTPS origin and public IPv4
DNS answers. We connect to a validated IP, preserving the original Host and
TLS SNI, so the HTTP client cannot resolve the hostname again after checking.
No environment proxy, redirect or environment-provided CA is used.
"""

import asyncio
import ipaddress
import re
import socket
import ssl

import certifi
import dns.asyncresolver
import dns.exception
import httpx

from .provider_urls import AIProviderURLError, ProviderTarget, provider_target


ADDRESS_ERROR = "Destination IA inaccessible ou non autorisée. Vérifiez la configuration réseau."
RESPONSE_ERROR = "Réponse du fournisseur IA invalide ou trop volumineuse."
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DNS_ADDRESSES = 32
_DNS_TIMEOUT = 3.0
_SPECIAL_IPV4 = (
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),  # deprecated 6to4 relay anycast
)
_PRIVATE_LOCAL = tuple(ipaddress.ip_network(item) for item in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_ENDPOINTS = {
    False: {("GET", "/models"), ("POST", "/chat/completions")},
    True: {("GET", "/api/tags"), ("POST", "/api/generate"), ("POST", "/api/chat")},
}


def _verified_tls_context() -> ssl.SSLContext:
    bundle = certifi.where()
    if not bundle:
        raise AIProviderURLError(ADDRESS_ERROR)
    # PROTOCOL_TLS_CLIENT requires certificate and hostname verification. Load
    # only certifi roots and do not read SSLKEYLOGFILE from the environment.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=bundle)
    return context


async def _resolve_ipv4(target: ProviderTarget) -> list[str]:
    """Resolve absolute public names without a search suffix or thread buildup."""
    if target.local_ollama:
        if target.hostname in {"localhost", "127.0.0.1"}:
            return ["127.0.0.1"]
        try:
            # Docker normally installs this fixed host-gateway name in /etc/hosts.
            loop = asyncio.get_running_loop()
            infos = await asyncio.wait_for(
                loop.getaddrinfo(target.hostname, target.port, family=socket.AF_INET, type=socket.SOCK_STREAM),
                timeout=_DNS_TIMEOUT,
            )
            return [item[4][0] for item in infos]
        except (OSError, TimeoutError):
            raise AIProviderURLError(ADDRESS_ERROR) from None
    try:
        # Absolute DNS query only; IPv6-only providers are intentionally not
        # supported. A public address is pinned after every DNS lookup.
        answers = await dns.asyncresolver.resolve(target.hostname + ".", "A", lifetime=_DNS_TIMEOUT, search=False)
        return [record.address for record in answers]
    except (dns.exception.DNSException, OSError, TimeoutError):
        raise AIProviderURLError(ADDRESS_ERROR) from None


def _approved_ipv4(target: ProviderTarget, values: list[str]) -> list[str]:
    """Reject the whole answer if any address can reach a restricted range."""
    if not values or len(values) > MAX_DNS_ADDRESSES:
        raise AIProviderURLError(ADDRESS_ERROR)
    approved: set[ipaddress.IPv4Address] = set()
    for value in values:
        try:
            ip = ipaddress.ip_address(value)
        except (TypeError, ValueError):
            raise AIProviderURLError(ADDRESS_ERROR) from None
        if not isinstance(ip, ipaddress.IPv4Address):
            raise AIProviderURLError(ADDRESS_ERROR)
        if target.local_ollama:
            if target.hostname in {"localhost", "127.0.0.1"}:
                allowed = ip == ipaddress.ip_address("127.0.0.1")
            else:
                allowed = ip == ipaddress.ip_address("127.0.0.1") or any(ip in network for network in _PRIVATE_LOCAL)
        else:
            allowed = (
                ip.is_global
                and not ip.is_private
                and not ip.is_loopback
                and not ip.is_link_local
                and not ip.is_multicast
                and not ip.is_reserved
                and not ip.is_unspecified
                and not any(ip in network for network in _SPECIAL_IPV4)
            )
        if not allowed:
            raise AIProviderURLError(ADDRESS_ERROR)
        approved.add(ip)
    return [str(ip) for ip in sorted(approved)]


async def request_provider(
    base_url: str | None,
    *,
    ollama: bool,
    method: str,
    endpoint: str,
    api_key: str | None = None,
    json: dict | None = None,
    timeout: int = 30,
) -> httpx.Response:
    """Request one fixed API endpoint, without exposing network error details."""
    if (method, endpoint) not in _ENDPOINTS[ollama] or (ollama and api_key):
        raise AIProviderURLError(ADDRESS_ERROR)
    if api_key is not None and (not isinstance(api_key, str) or re.fullmatch(r"[!-~]{1,2048}", api_key) is None):
        raise AIProviderURLError("Clé IA invalide.")
    target = provider_target(base_url, ollama=ollama)
    addresses = _approved_ipv4(target, await _resolve_ipv4(target))
    # Never use the hostname for the actual TCP connection: DNS can change
    # after validation. The original hostname is used for Host and TLS SNI.
    url = httpx.URL(f"{target.base_url}{endpoint}").copy_with(host=addresses[0])
    headers = {"Host": target.host_header, "Accept": "application/json", "Accept-Encoding": "identity"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        seconds = min(60, max(1, int(timeout)))
    except (TypeError, ValueError, OverflowError):
        seconds = 30
    timeouts = httpx.Timeout(seconds, connect=min(5, seconds))
    # httpx timeouts are per I/O operation; enforce a total deadline too so a
    # provider cannot keep a request open indefinitely by slowly streaming.
    async with asyncio.timeout(seconds):
        async with httpx.AsyncClient(
            timeout=timeouts, follow_redirects=False, trust_env=False, verify=_verified_tls_context(), http2=False,
        ) as client:
            async with client.stream(
                method, url, headers=headers, json=json, follow_redirects=False,
                extensions={"sni_hostname": target.hostname},
            ) as response:
                # Redirects are never followed, and error bodies may contain keys.
                if response.status_code < 200 or response.status_code >= 300:
                    return httpx.Response(status_code=response.status_code, request=response.request, content=b"")
                if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                    raise AIProviderURLError(RESPONSE_ERROR)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise AIProviderURLError(RESPONSE_ERROR)
                    content.extend(chunk)
                return httpx.Response(status_code=response.status_code, request=response.request, content=bytes(content))
