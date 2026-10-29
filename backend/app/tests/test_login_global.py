"""Global login mode: isolated ASGI and fake Redis, no network or hosted data."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.config import Settings, settings
from app.core.public_origin import public_https_origin
from app.database import get_db
from app.main import app
from app.routers import auth
from app.services.redis_store import (
    GLOBAL_LOGIN_ATTEMPTS,
    GLOBAL_LOGIN_WINDOW_SECONDS,
    LOGIN_ATTEMPTS,
    LoginRateLimited,
    RedisStore,
    get_redis_store,
)
from app.tests.asgi_helpers import WithClientIP
from app.tests.test_login_ip import EmptyDB, MemoryRedis, TEST_KEY


TEST_ORIGIN = "https://api.example.invalid"


def production_web(**changes):
    values = {
        "APP_ENV": "production",
        "SECRET_KEY": TEST_KEY,
        "DATABASE_URL": "postgresql://ci@127.0.0.1/unused",
        "REDIS_URL": "rediss://default:fake@redis.example.invalid/0",
        "ALLOW_PUBLIC_REGISTRATION": False,
        "CORS_ORIGINS": "",
        "LOGIN_LIMIT_SCOPE": "global",
        "CLIENT_IP_MODE": "",
        "CLIENT_IP_PROXY_HEADER": "",
        "CLIENT_IP_TRUSTED_PROXIES": "",
        "PUBLIC_API_ORIGIN": TEST_ORIGIN,
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_global_mode_is_explicit_and_does_not_require_proxy_ip():
    config = production_web()
    config.validate_runtime()
    config.validate_web_ip_settings()
    # It must never be silently selected as the default.
    with pytest.raises(ValueError, match="CLIENT_IP_MODE"):
        production_web(LOGIN_LIMIT_SCOPE="ip", PUBLIC_API_ORIGIN="").validate_web_ip_settings()


@pytest.mark.parametrize("changes", [
    {"CLIENT_IP_MODE": "direct"},
    {"CLIENT_IP_MODE": "trusted_proxy"},
    {"CLIENT_IP_PROXY_HEADER": "cf-connecting-ip"},
    {"CLIENT_IP_TRUSTED_PROXIES": "10.0.0.0/8"},
    {"PUBLIC_API_ORIGIN": ""},
    {"PUBLIC_API_ORIGIN": "http://api.example.invalid"},
    {"PUBLIC_API_ORIGIN": "https://user:password@api.example.invalid"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid/path"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid?x=1"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid#fragment"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid:"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid:65536"},
    {"PUBLIC_API_ORIGIN": "https://*.example.invalid"},
    {"PUBLIC_API_ORIGIN": "https://localhost"},
    {"PUBLIC_API_ORIGIN": "https://127.0.0.1"},
    {"PUBLIC_API_ORIGIN": "https://127.1"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid\\@evil.invalid"},
    {"PUBLIC_API_ORIGIN": "https://api.example.invalid\r\nX-Bad: yes"},
])
def test_global_production_rejects_mixed_or_unsafe_config(changes):
    with pytest.raises(ValueError):
        production_web(**changes).validate_web_ip_settings()


def test_global_web_import_fails_closed_before_network_when_origin_missing(tmp_path):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "APP_ENV": "production", "SECRET_KEY": TEST_KEY,
        "DATABASE_URL": "postgresql://ci@127.0.0.1:1/unused",
        "REDIS_URL": "rediss://default:fake-secret@redis.example.invalid/0",
        "ALLOW_PUBLIC_REGISTRATION": "false", "CORS_ORIGINS": "",
        "LOGIN_LIMIT_SCOPE": "global", "PUBLIC_API_ORIGIN": "",
        "CLIENT_IP_MODE": "", "CLIENT_IP_PROXY_HEADER": "", "CLIENT_IP_TRUSTED_PROXIES": "",
        "AI_ALLOW_LOCAL_OLLAMA": "false", "AI_ALLOWED_ORIGINS": "",
    })
    result = subprocess.run([sys.executable, "-c", "import app.main"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "PUBLIC_API_ORIGIN" in result.stderr
    assert "fake-secret" not in result.stdout + result.stderr and TEST_KEY not in result.stderr


def test_global_origin_canonicalization_and_separation():
    origin = public_https_origin("https://API.EXAMPLE.INVALID:8443/")
    assert origin.authority == "api.example.invalid:8443"
    assert origin.host == "api.example.invalid" and origin.port == 8443
    origin = public_https_origin("https://[2606:4700:4700::1111]")
    assert origin.port == 443 and origin.authority == "[2606:4700:4700::1111]"
    with pytest.raises(ValueError, match="PUBLIC_API_ORIGIN"):
        production_web(LOGIN_LIMIT_SCOPE="ip", CLIENT_IP_MODE="direct").validate_web_ip_settings()


def test_global_redis_counter_is_shared_and_atomic_in_memory():
    fake = MemoryRedis()
    first = RedisStore(fake, TEST_KEY, "test-global")
    second = RedisStore(fake, TEST_KEY, "test-global")

    def attempt(number):
        try:
            (first if number % 2 else second).record_global_login()
            return True
        except LoginRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(70)))
    assert sum(results) == GLOBAL_LOGIN_ATTEMPTS
    assert fake.values[first._login_global_key()][0] == 70
    assert first._login_global_key() == second._login_global_key()
    assert first._login_global_key() != first._login_ip_key("8.8.8.8")
    assert first._login_global_key() != first._login_key("user@example.com")


@pytest.fixture
def global_harness(monkeypatch):
    fake = MemoryRedis()
    store = RedisStore(fake, TEST_KEY, "test-global")
    for name, value in {
        "APP_ENV": "production", "LOGIN_LIMIT_SCOPE": "global", "CLIENT_IP_MODE": "",
        "CLIENT_IP_PROXY_HEADER": "", "CLIENT_IP_TRUSTED_PROXIES": "", "PUBLIC_API_ORIGIN": TEST_ORIGIN,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: EmptyDB())
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: store)
    monkeypatch.setattr(auth, "verify_password", lambda password, hashed: False)
    app.state.login_ip_guard.reset()
    clients = []

    def client(peer):
        result = TestClient(WithClientIP(app, peer))
        clients.append(result)
        return result

    yield fake, store, client
    for instance in clients:
        instance.close()
    app.state.login_ip_guard.reset()


def test_global_limit_covers_both_routes_different_peers_and_invalid_bodies(global_harness):
    fake, store, make_client = global_harness
    first, second, missing = make_client("8.8.8.8"), make_client("1.1.1.1"), make_client(None)
    clients = [first, second, missing]
    for number in range(GLOBAL_LOGIN_ATTEMPTS):
        headers = {
            "x-forwarded-for": f"192.0.2.{number + 1}",
            "cf-connecting-ip": f"192.0.2.{number + 1}",
            "Origin": "http://localhost:5173",
        }
        if number % 2:
            response = clients[number % 3].post("/api/v1/auth/login", data={}, headers=headers)
        else:
            response = clients[number % 3].post("/api/v1/auth/login-json", json={}, headers=headers)
        assert response.status_code == 422
    blocked = second.post("/api/v1/auth/login-json", headers={"Origin": "http://localhost:5173"}, json={})
    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= GLOBAL_LOGIN_WINDOW_SECONDS
    assert blocked.headers["cache-control"] == "no-store"
    assert blocked.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "retry-after" in blocked.headers["access-control-expose-headers"].lower()
    assert fake.values[store._login_global_key()][0] == GLOBAL_LOGIN_ATTEMPTS + 1
    calls = fake.calls
    for _ in range(70):
        assert first.post("/api/v1/auth/login", data={}).status_code == 429
    assert fake.calls == calls  # Local denial cache protects Redis in this process.
    assert missing.get("/health").status_code == 200
    assert missing.options("/api/v1/auth/login-json", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
    }).status_code == 200


def test_global_mode_preserves_separate_account_limit(global_harness):
    _, _, make_client = global_harness
    client = make_client("8.8.8.8")
    for _ in range(LOGIN_ATTEMPTS):
        assert client.post("/api/v1/auth/login-json", json={
            "email": "same@example.com", "password": "wrong",
        }).status_code == 401
    assert client.post("/api/v1/auth/login", data={
        "username": "same@example.com", "password": "wrong",
    }).status_code == 429
    assert client.post("/api/v1/auth/login-json", json={
        "email": "other@example.com", "password": "wrong",
    }).status_code == 401


def test_global_mode_fails_closed_when_redis_is_unavailable(global_harness, monkeypatch):
    _, _, make_client = global_harness

    class BrokenStore:
        def record_global_login(self):
            raise RedisError("fictitious-secret")

    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: BrokenStore())
    response = make_client(None).post("/api/v1/auth/login-json", json={})
    assert response.status_code == 503
    assert "fictitious-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_global_redirect_uses_only_configured_https_origin(global_harness):
    _, _, make_client = global_harness
    client = make_client(None)
    response = client.get("/health/?q=example", headers={
        "host": "attacker.example.invalid",
        "x-forwarded-host": "evil.example.invalid",
        "x-forwarded-proto": "http",
        "x-forwarded-for": "8.8.8.8",
    }, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == TEST_ORIGIN + "/health?q=example"
