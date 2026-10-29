"""IP login protection using in-memory ASGI requests and a fake Redis only."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from redis.exceptions import RedisError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings, settings
from app.core.client_ip import ClientIPError, canonical_client_ip, resolve_client_ip
from app.core.login_guard import LocalLoginGuard
from app.core.security import pwd_context, verify_password
from app.database import get_db
from app.main import app
from app.routers import auth
from app.services.redis_store import IP_LOGIN_ATTEMPTS, IP_LOGIN_WINDOW_SECONDS, LoginRateLimited, RedisStore, get_redis_store
from app.tests.asgi_helpers import WithClientIP


TEST_KEY = "fictitious-login-test-key-with-at-least-32-characters"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def policy(**overrides):
    values = {
        "APP_ENV": "test", "CLIENT_IP_MODE": "direct", "CLIENT_IP_PROXY_HEADER": "",
        "CLIENT_IP_TRUSTED_PROXIES": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def scope(peer="192.0.2.9", headers=()):
    return {"type": "http", "client": None if peer is None else (peer, 1234), "headers": list(headers)}


@pytest.mark.parametrize(("value", "expected"), [
    ("192.0.2.9", "192.0.2.9"),
    ("::ffff:192.0.2.9", "192.0.2.9"),
    ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
    ("  2001:db8::1  ", "2001:db8::1"),
])
def test_client_ip_is_canonicalized(value, expected):
    assert canonical_client_ip(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "not-an-ip", "1.2.3.4, 8.8.8.8", "1.2.3.4:80", "[::1]",
    "fe80::1%eth0", "0.0.0.0", "::", "224.0.0.1", "ff02::1", "255.255.255.255",
])
def test_invalid_or_ambiguous_addresses_are_rejected(value):
    with pytest.raises(ClientIPError):
        canonical_client_ip(value)


def test_direct_mode_ignores_all_forwarded_ip_headers():
    headers = [
        (b"x-forwarded-for", b"1.1.1.1"),
        (b"x-real-ip", b"1.1.1.1"),
        (b"cf-connecting-ip", b"1.1.1.1"),
    ]
    assert resolve_client_ip(scope("192.0.2.9", headers), policy()) == "192.0.2.9"
    with pytest.raises(ClientIPError):
        resolve_client_ip(scope(None, headers), policy())
    # A production deployment accidentally using direct mode behind a private
    # proxy fails closed instead of silently merging all clients into one IP.
    with pytest.raises(ClientIPError):
        resolve_client_ip(scope("10.2.3.4", headers), policy(APP_ENV="production"))
    assert resolve_client_ip(scope("8.8.8.8", headers), policy(APP_ENV="production")) == "8.8.8.8"


def test_only_the_explicit_header_from_a_trusted_peer_is_used():
    config = policy(
        CLIENT_IP_MODE="trusted_proxy", CLIENT_IP_PROXY_HEADER="cf-connecting-ip",
        CLIENT_IP_TRUSTED_PROXIES="10.2.0.0/16,2001:db8:100::/48",
    )
    headers = [(b"x-forwarded-for", b"1.1.1.1, 8.8.8.8"), (b"cf-connecting-ip", b"2001:db8::1")]
    assert resolve_client_ip(scope("10.2.3.4", headers), config) == "2001:db8::1"
    assert resolve_client_ip(scope("::ffff:10.2.3.4", headers), config) == "2001:db8::1"
    assert resolve_client_ip(scope("2001:db8:100::20", headers), config) == "2001:db8::1"
    with pytest.raises(ClientIPError):
        resolve_client_ip(scope("10.3.0.1", headers), config)


def test_production_proxy_rejects_non_public_forwarded_clients():
    config = policy(
        APP_ENV="production", CLIENT_IP_MODE="trusted_proxy", CLIENT_IP_PROXY_HEADER="x-real-ip",
        CLIENT_IP_TRUSTED_PROXIES="10.2.0.0/16",
    )
    assert resolve_client_ip(scope("10.2.3.4", [(b"x-real-ip", b"8.8.8.8")]), config) == "8.8.8.8"
    for address in (b"127.0.0.1", b"10.2.3.4", b"::1", b"169.254.169.254"):
        with pytest.raises(ClientIPError):
            resolve_client_ip(scope("10.2.3.4", [(b"x-real-ip", address)]), config)


@pytest.mark.parametrize("headers", [
    [],
    [(b"x-forwarded-for", b"8.8.8.8")],
    [(b"cf-connecting-ip", b"8.8.8.8"), (b"cf-connecting-ip", b"1.1.1.1")],
    [(b"cf-connecting-ip", b"8.8.8.8, 1.1.1.1")],
    [(b"cf-connecting-ip", b"not-an-ip")],
    [(b"cf-connecting-ip", b"\xff")],
])
def test_missing_duplicate_or_invalid_trusted_header_never_falls_back(headers):
    config = policy(
        CLIENT_IP_MODE="trusted_proxy", CLIENT_IP_PROXY_HEADER="cf-connecting-ip",
        CLIENT_IP_TRUSTED_PROXIES="10.2.0.0/16",
    )
    with pytest.raises(ClientIPError):
        resolve_client_ip(scope("10.2.3.4", headers), config)


def web_config(**overrides):
    values = {
        "APP_ENV": "production", "SECRET_KEY": TEST_KEY,
        "DATABASE_URL": "postgresql://ci@127.0.0.1/unused",
        "REDIS_URL": "rediss://default:fake@redis.example.invalid/0",
        "ALLOW_PUBLIC_REGISTRATION": False, "CORS_ORIGINS": "",
        "CLIENT_IP_MODE": "", "CLIENT_IP_PROXY_HEADER": "", "CLIENT_IP_TRUSTED_PROXIES": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_web_production_requires_an_explicit_ip_mode_but_offline_bootstrap_does_not():
    config = web_config()
    config.validate_runtime()  # No network; also used by the offline bootstrap.
    with pytest.raises(ValueError, match="CLIENT_IP_MODE"):
        config.validate_web_ip_settings()
    web_config(CLIENT_IP_MODE="direct").validate_web_ip_settings()
    web_config(APP_ENV="development").validate_web_ip_settings()
    web_config(
        CLIENT_IP_MODE="trusted_proxy", CLIENT_IP_PROXY_HEADER="x-real-ip",
        CLIENT_IP_TRUSTED_PROXIES="192.0.2.10,2001:db8::/48",
    ).validate_web_ip_settings()


@pytest.mark.parametrize("changes", [
    {"CLIENT_IP_MODE": "trusted_proxy"},
    {"CLIENT_IP_MODE": "trusted_proxy", "CLIENT_IP_PROXY_HEADER": "x-real-ip"},
    {"CLIENT_IP_MODE": "trusted_proxy", "CLIENT_IP_PROXY_HEADER": "x-real-ip", "CLIENT_IP_TRUSTED_PROXIES": "0.0.0.0/0"},
    {"CLIENT_IP_MODE": "trusted_proxy", "CLIENT_IP_PROXY_HEADER": "x-real-ip", "CLIENT_IP_TRUSTED_PROXIES": "::/0"},
    {"CLIENT_IP_MODE": "trusted_proxy", "CLIENT_IP_PROXY_HEADER": "x-real-ip", "CLIENT_IP_TRUSTED_PROXIES": "*"},
    {"CLIENT_IP_MODE": "trusted_proxy", "CLIENT_IP_PROXY_HEADER": "x-real-ip", "CLIENT_IP_TRUSTED_PROXIES": "10.0.0.1/8"},
    {"CLIENT_IP_MODE": "trusted_proxy", "CLIENT_IP_PROXY_HEADER": "x-real-ip", "CLIENT_IP_TRUSTED_PROXIES": "10.0.0.1,"},
    {"CLIENT_IP_MODE": "direct", "CLIENT_IP_PROXY_HEADER": "x-real-ip"},
    {"CLIENT_IP_MODE": "direct", "CLIENT_IP_TRUSTED_PROXIES": "10.0.0.1"},
])
def test_invalid_or_unbounded_proxy_trust_is_rejected(changes):
    with pytest.raises(ValueError):
        web_config(**changes).validate_web_ip_settings()


def test_production_web_import_fails_before_connecting_if_ip_mode_is_missing(tmp_path):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(BACKEND_DIR), "APP_ENV": "production", "SECRET_KEY": TEST_KEY,
        "DATABASE_URL": "postgresql://ci@127.0.0.1:1/unused",
        "REDIS_URL": "rediss://default:fake@redis.example.invalid/0", "ALLOW_PUBLIC_REGISTRATION": "false",
        "CLIENT_IP_MODE": "", "CLIENT_IP_PROXY_HEADER": "", "CLIENT_IP_TRUSTED_PROXIES": "",
        "CORS_ORIGINS": "", "AI_ALLOW_LOCAL_OLLAMA": "false", "AI_ALLOWED_ORIGINS": "",
    })
    result = subprocess.run([sys.executable, "-c", "import app.main"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "CLIENT_IP_MODE" in result.stderr
    assert TEST_KEY not in result.stderr and "fake@" not in result.stderr


def test_all_bundled_uvicorn_commands_preserve_the_socket_peer():
    root = BACKEND_DIR.parent
    for path in (root / "backend/Dockerfile", root / "docker-compose.yml", root / "docker-compose.prod.yml"):
        content = path.read_text(encoding="utf-8")
        assert "uvicorn app.main:app" in content or '"uvicorn", "app.main:app"' in content
        assert "--no-proxy-headers" in content


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self):
        return self.now


def test_local_guard_bounds_memory_and_does_not_persist_raw_addresses():
    clock = Clock()
    guard = LocalLoginGuard(limit=20, window=60, capacity=2, clock=clock)
    guard.remember_blocked("192.0.2.1", 5)
    guard.remember_blocked("192.0.2.2", 6)
    assert guard.precheck("192.0.2.1") == 5
    guard.remember_blocked("192.0.2.3", 7)
    assert len(guard._blocked) == 2
    assert all(b"192.0.2" not in key for key in guard._blocked)
    assert guard.precheck("192.0.2.2") is None  # LRU eviction is explicitly best-effort.
    clock.now += 8
    assert guard.precheck("192.0.2.1") is None
    assert guard.precheck("192.0.2.3") is None


def test_local_global_budget_is_atomic_and_expires():
    clock = Clock()
    guard = LocalLoginGuard(limit=20, window=10, capacity=4, clock=clock)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda n: guard.precheck(f"192.0.2.{n + 1}"), range(50)))
    assert results.count(None) == 20
    assert results.count(10) == 30
    clock.now += 10
    assert guard.precheck("192.0.2.250") is None


def test_cached_ip_denials_do_not_exhaust_other_clients_local_budget():
    clock = Clock()
    guard = LocalLoginGuard(limit=2, window=60, capacity=2, clock=clock)
    guard.remember_blocked("192.0.2.1", 30)
    for _ in range(100):
        assert guard.precheck("192.0.2.1") == 30
    assert guard.precheck("192.0.2.2") is None
    assert guard.precheck("192.0.2.3") is None
    assert guard.precheck("192.0.2.4") == 60


def test_local_denial_is_never_cached_longer_than_the_ip_window():
    clock = Clock()
    guard = LocalLoginGuard(limit=20, window=60, capacity=2, clock=clock)
    guard.remember_blocked("192.0.2.1", IP_LOGIN_WINDOW_SECONDS * 100)
    assert guard.precheck("192.0.2.1") == IP_LOGIN_WINDOW_SECONDS
    clock.now += IP_LOGIN_WINDOW_SECONDS
    assert guard.precheck("192.0.2.1") is None


class MemoryRedis:
    """Thread-safe model of the one-key Lua counter; no real Redis process."""

    def __init__(self):
        self.lock = threading.Lock()
        self.values = {}
        self.calls = 0

    def eval(self, script, key_count, key, window):
        assert key_count == 1 and "redis.call('INCR'" in script
        with self.lock:
            self.calls += 1
            now = time.monotonic()
            count, expiry = self.values.get(key, (0, now + int(window)))
            if expiry <= now:
                count, expiry = 0, now + int(window)
            count += 1
            self.values[key] = count, expiry
            return count, max(1, math.ceil(expiry - now))


def test_ip_counter_is_shared_across_concurrent_calls_and_pseudonymized():
    fake = MemoryRedis()
    first = RedisStore(fake, TEST_KEY, "test-ip")
    second = RedisStore(fake, TEST_KEY, "test-ip")
    address = "192.0.2.93"

    def attempt(number):
        try:
            (first if number % 2 else second).record_login_ip(address)
            return True
        except LoginRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        accepted = list(pool.map(attempt, range(70)))
    assert sum(accepted) == IP_LOGIN_ATTEMPTS
    key = first._login_ip_key(address)
    assert address not in key
    assert fake.values[key][0] == 70
    assert first._login_ip_key("::ffff:192.0.2.93") == key
    assert first._login_ip_key("2001:db8::1") == first._login_ip_key("2001:0db8:0:0:0:0:0:1")


class EmptyQuery:
    def filter(self, *args):
        return self

    def first(self):
        return None


class EmptyDB:
    def query(self, model):
        return EmptyQuery()


@pytest.fixture
def harness(monkeypatch):
    fake = MemoryRedis()
    store = RedisStore(fake, TEST_KEY, "test-ip")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "CLIENT_IP_MODE", "direct")
    monkeypatch.setattr(settings, "CLIENT_IP_PROXY_HEADER", "")
    monkeypatch.setattr(settings, "CLIENT_IP_TRUSTED_PROXIES", "")
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: EmptyDB())
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: store)
    monkeypatch.setattr(auth, "verify_password", lambda password, hashed: False)
    app.state.login_ip_guard.reset()
    clients = []

    def client(peer="192.0.2.10"):
        instance = TestClient(WithClientIP(app, peer))
        clients.append(instance)
        return instance

    yield SimpleNamespace(fake=fake, store=store, client=client)
    for instance in clients:
        instance.close()
    app.state.login_ip_guard.reset()


def test_distinct_identifiers_share_one_ip_limit_across_both_routes(harness):
    client = harness.client()
    for n in range(IP_LOGIN_ATTEMPTS):
        if n % 2:
            result = client.post("/api/v1/auth/login", data={"username": f"no{n}@example.com", "password": "wrong"})
        else:
            result = client.post("/api/v1/auth/login-json", json={"email": f"no{n}@example.com", "password": "wrong"})
        assert result.status_code == 401
        assert "x-process-time" not in result.headers
    blocked = client.post("/api/v1/auth/login-json", json={"email": "another@example.com", "password": "wrong"})
    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= IP_LOGIN_WINDOW_SECONDS
    assert blocked.headers["Cache-Control"] == "no-store"
    assert "192.0.2.10" not in blocked.text and "wrong" not in blocked.text
    calls = harness.fake.calls
    for _ in range(70):
        assert client.post("/api/v1/auth/login", data={"username": "another@example.com", "password": "wrong"}).status_code == 429
    assert harness.fake.calls == calls  # Cached denials do not consume Redis or other clients' local budget.
    assert harness.client("192.0.2.11").post("/api/v1/auth/login-json", json={"email": "other@example.com", "password": "wrong"}).status_code == 401


def test_invalid_json_is_limited_before_validation_and_cors_survives(harness):
    client = harness.client()
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}
    for _ in range(IP_LOGIN_ATTEMPTS):
        result = client.post("/api/v1/auth/login-json", headers=headers, content="{")
        assert result.status_code == 422
    result = client.post("/api/v1/auth/login-json", headers=headers, content="{")
    assert result.status_code == 429
    assert result.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "retry-after" in result.headers["access-control-expose-headers"].lower()
    assert "retry-after" in result.headers and "x-process-time" not in result.headers
    assert len(harness.fake.values) == 1  # Only the IP key; malformed bodies cannot create account keys.


def test_local_budget_rejects_new_ips_before_redis_when_flooded(harness):
    for n in range(60):
        result = harness.client(f"192.0.2.{n + 1}").post("/api/v1/auth/login-json", json={})
        assert result.status_code == 422
    calls = harness.fake.calls
    blocked = harness.client("192.0.2.200").post("/api/v1/auth/login-json", json={})
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert harness.fake.calls == calls
    assert harness.client("192.0.2.201").get("/health").status_code == 200


def test_ipv4_mapped_ipv6_shares_the_same_ip_bucket(harness):
    mapped, ordinary = harness.client("::ffff:192.0.2.42"), harness.client("192.0.2.42")
    for _ in range(IP_LOGIN_ATTEMPTS):
        assert mapped.post("/api/v1/auth/login-json", json={}).status_code == 422
    assert ordinary.post("/api/v1/auth/login-json", json={}).status_code == 429
    assert harness.store._login_ip_key("::ffff:192.0.2.42") == harness.store._login_ip_key("192.0.2.42")


def test_spoofed_xff_does_not_change_the_proxy_client_bucket(harness, monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_MODE", "trusted_proxy")
    monkeypatch.setattr(settings, "CLIENT_IP_PROXY_HEADER", "cf-connecting-ip")
    monkeypatch.setattr(settings, "CLIENT_IP_TRUSTED_PROXIES", "10.2.0.0/16")
    client = harness.client("10.2.3.4")
    for n in range(IP_LOGIN_ATTEMPTS):
        result = client.post("/api/v1/auth/login-json", headers={
            "cf-connecting-ip": "8.8.8.8", "x-forwarded-for": f"192.0.2.{n + 1}",
        }, json={})
        assert result.status_code == 422
    assert client.post("/api/v1/auth/login-json", headers={
        "cf-connecting-ip": "8.8.8.8", "x-forwarded-for": "192.0.2.200",
    }, json={}).status_code == 429
    assert "8.8.8.8" not in harness.store._login_ip_key("8.8.8.8")
    assert harness.client("10.3.1.1").post("/api/v1/auth/login-json", headers={
        "cf-connecting-ip": "8.8.8.8",
    }, json={}).status_code == 503


def test_misconfigured_uvicorn_rewritten_client_is_rejected_in_production(harness, monkeypatch):
    # Uvicorn 0.30.6 with '*' would otherwise pick a caller-supplied XFF IP.
    # Its rewrite sets the peer port to zero, which our production policy
    # rejects. The deployment flag remains mandatory as the primary defense.
    monkeypatch.setattr(settings, "APP_ENV", "production")
    proxied = ProxyHeadersMiddleware(app, trusted_hosts="*")
    client = TestClient(WithClientIP(proxied, "8.8.8.8"))
    try:
        result = client.post("/api/v1/auth/login-json", headers={"x-forwarded-for": "1.1.1.1"}, json={})
        assert result.status_code == 503
        assert harness.fake.calls == 0
    finally:
        client.close()


def test_direct_mode_header_rotation_cannot_change_the_socket_bucket(harness):
    client = harness.client()
    for n in range(IP_LOGIN_ATTEMPTS):
        result = client.post("/api/v1/auth/login-json", headers={
            "x-forwarded-for": f"192.0.2.{n + 20}", "cf-connecting-ip": f"192.0.2.{n + 20}",
        }, json={})
        assert result.status_code == 422
    assert client.post("/api/v1/auth/login-json", headers={"cf-connecting-ip": "192.0.2.200"}, json={}).status_code == 429


def test_redis_failure_or_missing_proxy_identity_fails_closed_without_secrets(harness, monkeypatch):
    class BrokenStore:
        def record_login_ip(self, client_ip):
            raise RedisError("fictitious-redis-password")

    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: BrokenStore())
    response = harness.client().post("/api/v1/auth/login-json", json={"password": "fictitious-password"})
    assert response.status_code == 503
    assert "fictitious" not in response.text and "192.0.2.10" not in response.text
    assert response.headers["Cache-Control"] == "no-store" and "x-process-time" not in response.headers

    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: harness.store)
    monkeypatch.setattr(settings, "CLIENT_IP_MODE", "trusted_proxy")
    monkeypatch.setattr(settings, "CLIENT_IP_PROXY_HEADER", "x-real-ip")
    monkeypatch.setattr(settings, "CLIENT_IP_TRUSTED_PROXIES", "10.2.0.0/16")
    before = harness.fake.calls
    response = harness.client("10.2.3.4").post("/api/v1/auth/login-json", headers={"x-forwarded-for": "8.8.8.8"}, json={})
    assert response.status_code == 503 and harness.fake.calls == before


def test_missing_redis_in_production_does_not_block_health_or_preflight(harness, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: None)
    client = harness.client("8.8.8.8")
    assert client.post("/api/v1/auth/login-json", json={}).status_code == 503
    assert client.get("/health").status_code == 200
    assert client.options("/api/v1/auth/login-json", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
    }).status_code == 200


def test_trusted_https_proxy_keeps_redirects_https_without_trusting_proto(harness, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "CLIENT_IP_MODE", "trusted_proxy")
    monkeypatch.setattr(settings, "CLIENT_IP_PROXY_HEADER", "x-real-ip")
    monkeypatch.setattr(settings, "CLIENT_IP_TRUSTED_PROXIES", "10.2.0.0/16")
    result = harness.client("10.2.3.4").post("/api/v1/auth/login-json/", headers={
        "x-real-ip": "8.8.8.8", "x-forwarded-proto": "http",
    }, json={}, follow_redirects=False)
    assert result.status_code == 307
    assert result.headers["location"].startswith("https://")
    assert "x-process-time" not in result.headers


def test_unknown_and_inactive_users_do_dummy_work_and_never_authenticate(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    calls = []

    def pretend_verification(password, hashed):
        calls.append((password, hashed))
        return True  # Even a match against the public dummy must be rejected.

    monkeypatch.setattr(auth, "verify_password", pretend_verification)
    for user in (None, SimpleNamespace(id=1, hashed_password="real-user-hash", session_nonce=None, is_active=False)):
        class Query:
            def filter(self, *args): return self
            def first(self): return user

        class DB:
            def query(self, model): return Query()

        with pytest.raises(HTTPException) as error:
            auth._login("fictitious@example.com", "fictitious-password", DB(), None)
        assert error.value.status_code == 401
    assert calls == [("fictitious-password", auth._DUMMY_LOGIN_HASH)] * 2


def test_dummy_hash_has_the_current_bcrypt_work_factor():
    assert pwd_context.identify(auth._DUMMY_LOGIN_HASH) == "bcrypt"
    assert not pwd_context.needs_update(auth._DUMMY_LOGIN_HASH)
    assert verify_password("not-a-credential-used-for-dummy-verification", auth._DUMMY_LOGIN_HASH)
