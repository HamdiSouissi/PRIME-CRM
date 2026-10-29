"""SSRF policy tests use only fictitious DNS, addresses and HTTP transports."""

import asyncio
from types import SimpleNamespace

import dns.exception
import httpx
import pytest

from app.config import Settings, settings
from app.services.ai_service import egress
from app.services.ai_service.provider_urls import (
    AIProviderURLError,
    parse_allowed_origins,
    provider_target,
)


ORIGIN = "https://provider.example.invalid"
BASE = ORIGIN + "/v1"
PUBLIC_IP = "93.184.216.34"
FAKE_KEY = "sk-fictitious-provider-key-9283"


@pytest.fixture(autouse=True)
def isolated_policy(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "AI_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", False)


def runtime_settings(**overrides):
    values = {
        "_env_file": None,
        "APP_ENV": "production",
        "SECRET_KEY": "fictitious-test-secret-with-many-distinct-characters-4827",
        "DATABASE_URL": "postgresql://fake:fake@127.0.0.1:1/unused",
        "REDIS_URL": "rediss://default:fake@redis.example.invalid:6379/0",
        "CORS_ORIGINS": "",
        "ALLOW_PUBLIC_REGISTRATION": False,
        "AI_ALLOWED_ORIGINS": "",
        "AI_ALLOW_LOCAL_OLLAMA": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_empty_environment_allowlist_overrides_older_dotenv(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("AI_ALLOWED_ORIGINS=https://provider.example.invalid\n")
    monkeypatch.setenv("AI_ALLOWED_ORIGINS", "")
    configuration = Settings(_env_file=dotenv)
    assert configuration.AI_ALLOWED_ORIGINS == ""


def test_fail_closed_by_default_and_validate_runtime_without_connecting(monkeypatch):
    monkeypatch.setattr(settings, "AI_ALLOWED_ORIGINS", "")
    with pytest.raises(AIProviderURLError):
        provider_target(BASE, ollama=False)
    with pytest.raises(AIProviderURLError):
        provider_target("http://localhost:11434", ollama=True)
    runtime_settings().validate_runtime()
    with pytest.raises(ValueError, match="AI_ALLOW_LOCAL_OLLAMA"):
        runtime_settings(AI_ALLOW_LOCAL_OLLAMA=True).validate_runtime()
    with pytest.raises(ValueError, match="AI_ALLOWED_ORIGINS"):
        runtime_settings(AI_ALLOWED_ORIGINS="https://*.example.invalid").validate_runtime()


@pytest.mark.parametrize("invalid", [
    "https://*.example.invalid", "http://provider.example.invalid", "https://127.0.0.1",
    "https://[::1]", "https://user:secret@provider.example.invalid", "https://provider.example.invalid/path",
    "https://provider.example.invalid?query=secret", "https://provider.example.invalid#fragment",
    "https://provider.example.invalid:", "https://provider.example.invalid:65536", "https://provider.example.invalid,",
    "https://provider.example.invalid\n", "https://provider.example.invalid/../../", "file:///etc/passwd",
    "https://localhost", "https://provider.example.invalid.", "https://2130706433",
])
def test_invalid_allowlist_entries_fail_closed(invalid):
    # Surrounding whitespace on a comma-separated entry is deliberately allowed.
    if invalid.endswith("\n"):
        invalid = invalid + "bad"
    with pytest.raises(AIProviderURLError):
        parse_allowed_origins(invalid)


def test_origins_are_exact_normalized_hosts_and_ports():
    assert parse_allowed_origins(" HTTPS://Provider.Example.Invalid:443/ , https://provider.example.invalid:8443 ") == {
        ORIGIN, ORIGIN + ":8443"
    }
    assert provider_target("https://PROVIDER.EXAMPLE.INVALID:443/v1/", ollama=False).base_url == BASE
    for url in (
        "https://sub.provider.example.invalid/v1", "https://provider.example.invalid.attacker.invalid/v1",
        "https://provider.example.invalid:8443/v1", "http://provider.example.invalid/v1",
        "https://provider.example.invalid./v1", "https://user:password@provider.example.invalid/v1",
        "https://provider.example.invalid/v1?key=secret", "https://provider.example.invalid/v1#fragment",
        "https://provider.example.invalid\\@attacker.invalid/v1", "https://127.0.0.1:443/v1",
        "https://[::1]/v1", "https://169.254.169.254/v1", "https://2130706433/v1",
    ):
        with pytest.raises(AIProviderURLError):
            provider_target(url, ollama=False)


def test_local_ollama_is_explicit_development_only_and_narrow(monkeypatch):
    for env in ("production", "test"):
        monkeypatch.setattr(settings, "APP_ENV", env)
        monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", True)
        with pytest.raises(AIProviderURLError):
            provider_target("http://localhost:11434", ollama=True)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", False)
    with pytest.raises(AIProviderURLError):
        provider_target("http://localhost:11434", ollama=True)
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", True)
    for host in ("localhost", "127.0.0.1", "host.docker.internal"):
        assert provider_target(f"http://{host}:11434", ollama=True).local_ollama
    for url in (
        "http://localhost:11435", "http://localhost:11434/path", "http://127.0.0.2:11434",
        "http://169.254.169.254:11434", "http://10.0.0.1:11434", "http://evil.invalid:11434",
        "http://user:secret@localhost:11434", "http://localhost:11434?x=1",
        "http://localhost:11434#fragment", "http://[::1]:11434",
    ):
        with pytest.raises(AIProviderURLError):
            provider_target(url, ollama=True)
    with pytest.raises(AIProviderURLError):
        provider_target("http://127.0.0.1:11434", ollama=False)


@pytest.mark.parametrize("address", [
    "0.0.0.0", "10.1.2.3", "127.0.0.1", "169.254.169.254", "172.16.4.2", "192.168.1.1",
    "100.64.1.2", "192.0.0.9", "192.88.99.1", "198.18.1.2", "192.0.2.5", "203.0.113.10",
    "224.0.0.1", "240.0.0.1", "255.255.255.255", "::1", "::ffff:8.8.8.8", "64:ff9b::a9fe:a9fe",
    "not-an-address",
])
def test_restricted_address_or_mixed_dns_answers_are_denied(address):
    target = provider_target(BASE, ollama=False)
    with pytest.raises(AIProviderURLError):
        egress._approved_ipv4(target, [address])
    with pytest.raises(AIProviderURLError):
        egress._approved_ipv4(target, [PUBLIC_IP, address])


def test_address_answer_limits_and_local_gateway_checks(monkeypatch):
    target = provider_target(BASE, ollama=False)
    assert egress._approved_ipv4(target, [PUBLIC_IP, PUBLIC_IP]) == [PUBLIC_IP]
    for values in ([], [PUBLIC_IP] * (egress.MAX_DNS_ADDRESSES + 1)):
        with pytest.raises(AIProviderURLError):
            egress._approved_ipv4(target, values)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", True)
    local = provider_target("http://host.docker.internal:11434", ollama=True)
    assert egress._approved_ipv4(local, ["172.17.0.1"]) == ["172.17.0.1"]
    for value in ("169.254.169.254", "0.0.0.0", PUBLIC_IP, "224.0.0.1"):
        with pytest.raises(AIProviderURLError):
            egress._approved_ipv4(local, [value])
    loopback = provider_target("http://localhost:11434", ollama=True)
    with pytest.raises(AIProviderURLError):
        egress._approved_ipv4(loopback, ["127.0.0.2"])


@pytest.mark.asyncio
async def test_public_dns_is_absolute_ipv4_only_and_fails_closed(monkeypatch):
    seen = []

    async def fake_dns(name, record_type, **kwargs):
        seen.append((name, record_type, kwargs))
        return [SimpleNamespace(address=PUBLIC_IP)]

    monkeypatch.setattr(egress.dns.asyncresolver, "resolve", fake_dns)
    target = provider_target(BASE, ollama=False)
    assert await egress._resolve_ipv4(target) == [PUBLIC_IP]
    assert seen == [("provider.example.invalid.", "A", {"lifetime": 3.0, "search": False})]

    async def broken_dns(*args, **kwargs):
        raise dns.exception.Timeout("fictitious DNS details")

    monkeypatch.setattr(egress.dns.asyncresolver, "resolve", broken_dns)
    with pytest.raises(AIProviderURLError) as error:
        await egress._resolve_ipv4(target)
    assert "fictitious" not in str(error.value)


def mocked_client(monkeypatch, handler):
    observed_options = []
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        observed_options.append(kwargs.copy())
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return observed_options


@pytest.mark.asyncio
async def test_pins_ip_host_and_sni_blocks_redirects_and_ignores_proxies(monkeypatch):
    observed = []

    async def resolve(target):
        assert target.hostname == "provider.example.invalid"
        return [PUBLIC_IP]

    def handler(request):
        observed.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}, text=FAKE_KEY)

    monkeypatch.setattr(egress, "_resolve_ipv4", resolve)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    options = mocked_client(monkeypatch, handler)
    response = await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert response.status_code == 302 and response.content == b""
    assert len(observed) == 1
    req = observed[0]
    assert req.url.host == PUBLIC_IP and req.url.path == "/v1/models"
    assert req.headers["host"] == "provider.example.invalid"
    assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert req.extensions["sni_hostname"] == "provider.example.invalid"
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False
    assert options[0]["verify"].check_hostname is True
    assert FAKE_KEY not in response.text


@pytest.mark.asyncio
async def test_rebinding_and_bad_dns_never_reach_http(monkeypatch):
    observed = []
    answers = iter([[PUBLIC_IP], ["169.254.169.254"], [PUBLIC_IP, "127.0.0.1"]])

    async def resolve(target):
        return next(answers)

    monkeypatch.setattr(egress, "_resolve_ipv4", resolve)
    mocked_client(monkeypatch, lambda request: (observed.append(request) or httpx.Response(200, json={"data": []})))
    await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    for _ in range(2):
        with pytest.raises(AIProviderURLError):
            await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert len(observed) == 1 and observed[0].url.host == PUBLIC_IP


@pytest.mark.asyncio
async def test_bad_endpoint_key_encoding_and_response_size_are_rejected(monkeypatch):
    called = []

    async def resolve(target):
        return [PUBLIC_IP]

    monkeypatch.setattr(egress, "_resolve_ipv4", resolve)
    body = {"value": b"x" * (egress.MAX_RESPONSE_BYTES + 1), "headers": {}}
    mocked_client(monkeypatch, lambda request: (called.append(request) or httpx.Response(200, stream=httpx.ByteStream(body["value"]), headers=body["headers"])))
    with pytest.raises(AIProviderURLError):
        await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/latest/meta-data", api_key=FAKE_KEY)
    with pytest.raises(AIProviderURLError):
        await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key="secret\r\nInjected: x")
    assert called == []
    with pytest.raises(AIProviderURLError):
        await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    body["value"], body["headers"] = b"compressed", {"Content-Encoding": "gzip"}
    with pytest.raises(AIProviderURLError):
        await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert len(called) == 2


@pytest.mark.asyncio
async def test_total_deadline_cancels_slow_stream_even_if_data_keeps_arriving(monkeypatch):
    async def resolve(target):
        return [PUBLIC_IP]

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.sleep(1.5)
            yield b"}"

    monkeypatch.setattr(egress, "_resolve_ipv4", resolve)
    mocked_client(monkeypatch, lambda request: httpx.Response(200, stream=SlowStream()))
    with pytest.raises(TimeoutError):
        await egress.request_provider(BASE, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY, timeout=1)
