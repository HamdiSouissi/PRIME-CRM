"""Fail-closed configuration and Redis failure handling without a network."""

import os
from pathlib import Path
import ssl
import subprocess
import sys

import pytest
import redis
from fastapi import HTTPException
from redis.exceptions import RedisError

from app import main as main_module
from app.config import Settings, settings
from app.routers.admin import health_check
from app.routers.auth import enforce_login_limit
from app.services import redis_store as redis_service
from app.services.redis_store import CertifiTLSConnection, LoginRateLimited, create_redis_store


TEST_KEY = "ci-only-signing-key-with-more-than-thirty-two-characters"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def production_config(**overrides):
    values = {
        "APP_ENV": "production",
        "SECRET_KEY": TEST_KEY,
        "DATABASE_URL": "postgresql://ci@127.0.0.1/unused",
        "ALLOW_PUBLIC_REGISTRATION": False,
        "CORS_ORIGINS": "",
        "REDIS_URL": "rediss://default:test-only-password@redis.example.invalid:6379/0",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("redis_url", [
    "",
    "redis://default:test-only-password@redis.example.invalid:6379/0",
    "rediss://redis.example.invalid:6379/0",
    "rediss://default:test-only-password@/0",
    "rediss://default:test-only-password@redis.example.invalid:notaport/0",
    "rediss://default:test-only-password@redis.example.invalid:6379/1",
    "rediss://default:test-only-password@redis.example.invalid:6379/0?ssl_check_hostname=false",
    "rediss://default:test-only-password@redis.example.invalid:6379/0?ssl_cert_reqs=none",
])
def test_production_requires_authenticated_tls_redis(redis_url):
    with pytest.raises(ValueError, match="REDIS_URL") as error:
        production_config(REDIS_URL=redis_url).validate_runtime()
    assert "test-only-password" not in str(error.value)


def test_production_accepts_redis_tls_url_and_client_checks_hostname():
    url = "rediss://default:test-only-password@redis.example.invalid:6379/0"
    production_config(REDIS_URL=url).validate_runtime()
    store = create_redis_store(url, TEST_KEY)
    pool = store.client.connection_pool
    assert pool.connection_class is CertifiTLSConnection
    assert pool.connection_kwargs["socket_connect_timeout"] == 2
    assert pool.connection_kwargs["socket_timeout"] == 2
    store.close()


def test_redis_tls_uses_only_the_explicit_bundle_and_requires_hostname(monkeypatch):
    fake_socket = object()

    class FakeContext:
        check_hostname = False
        verify_mode = None
        keylog_filename = "must-not-record-tls-secrets"

        def wrap_socket(self, sock, server_hostname):
            assert sock is fake_socket and server_hostname == "redis.example.invalid"
            assert self.check_hostname is True and self.verify_mode == ssl.CERT_REQUIRED
            assert self.keylog_filename is None
            return "wrapped"

    context = FakeContext()
    monkeypatch.setattr(redis_service.certifi, "where", lambda: "private-fake-ca-file")

    def make_context(*, cafile):
        assert cafile == "private-fake-ca-file"
        return context

    monkeypatch.setattr(redis_service.ssl, "create_default_context", make_context)
    monkeypatch.setattr(redis.connection.Connection, "_connect", lambda self: fake_socket)
    assert CertifiTLSConnection(host="redis.example.invalid")._connect() == "wrapped"


def test_redis_tls_rejects_an_empty_bundle_before_opening_socket(monkeypatch):
    monkeypatch.setattr(redis_service.certifi, "where", lambda: "")
    monkeypatch.setattr(redis.connection.Connection, "_connect", lambda self: pytest.fail("Socket must not open"))
    with pytest.raises(ssl.SSLError, match="CA bundle"):
        CertifiTLSConnection(host="redis.example.invalid")._connect()


def test_redis_tls_closes_the_socket_if_the_handshake_fails(monkeypatch):
    class FakeSocket:
        closed = False

        def close(self): self.closed = True

    class FakeContext:
        def wrap_socket(self, *args, **kwargs):
            raise ssl.SSLError("fake test error")

    sock = FakeSocket()
    monkeypatch.setattr(redis_service.certifi, "where", lambda: "private-fake-ca-file")
    monkeypatch.setattr(redis_service.ssl, "create_default_context", lambda **kwargs: FakeContext())
    monkeypatch.setattr(redis.connection.Connection, "_connect", lambda self: sock)
    with pytest.raises(ssl.SSLError, match="fake test error"):
        CertifiTLSConnection(host="redis.example.invalid")._connect()
    assert sock.closed


def test_development_may_run_without_redis_but_rejects_malformed_url():
    production_config(APP_ENV="development", DATABASE_URL="sqlite:///:memory:", REDIS_URL="").validate_runtime()
    with pytest.raises(ValueError, match="REDIS_URL"):
        production_config(APP_ENV="development", DATABASE_URL="sqlite:///:memory:", REDIS_URL="http://invalid").validate_runtime()


def test_bootstrap_refuses_missing_production_redis_without_printing_credentials(tmp_path):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(BACKEND_DIR),
        "APP_ENV": "production",
        "SECRET_KEY": TEST_KEY,
        "DATABASE_URL": "postgresql://ci:test-database-password@127.0.0.1:1/unused",
        "REDIS_URL": "",
        "ALLOW_PUBLIC_REGISTRATION": "false",
        "CORS_ORIGINS": "",
    })
    result = subprocess.run([sys.executable, "-m", "app.bootstrap"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "REDIS_URL" in result.stderr
    assert "test-database-password" not in result.stdout + result.stderr
    assert TEST_KEY not in result.stdout + result.stderr


def test_login_fails_closed_on_redis_error_without_disclosing_details(monkeypatch):
    class BrokenStore:
        def record_login(self, identifier):
            raise RedisError("redis fake-secret-value")

    with pytest.raises(HTTPException) as error:
        enforce_login_limit("person@example.com", BrokenStore())
    assert error.value.status_code == 503
    assert "fake-secret-value" not in str(error.value.detail)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(HTTPException) as error:
        enforce_login_limit("person@example.com", None)
    assert error.value.status_code == 503


def test_rate_limit_returns_retry_after_without_identifier():
    class BlockedStore:
        def record_login(self, identifier):
            raise LoginRateLimited(123)

    with pytest.raises(HTTPException) as error:
        enforce_login_limit("person@example.com", BlockedStore())
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "123"}
    assert "person@example.com" not in str(error.value.detail)


def test_admin_health_sanitizes_database_errors():
    class BrokenDatabase:
        def execute(self, statement):
            raise RuntimeError("database fake-secret-value")

    result = health_check(db=BrokenDatabase(), current_user=None)
    assert result["status"] == "degraded"
    assert result["database"] == "indisponible"
    assert "fake-secret-value" not in str(result)


def test_startup_refuses_unwritable_redis_without_leaking_errors(monkeypatch):
    class FakeDB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def query(self, *args): return self
        def first(self): return (1,)

    class BrokenStore:
        def check_writable(self):
            raise RedisError("redis fake-secret-value")

    monkeypatch.setattr(main_module, "SessionLocal", FakeDB)
    monkeypatch.setattr(main_module, "require_current_schema", lambda db: None)
    monkeypatch.setattr(main_module, "get_redis_store", lambda: BrokenStore())
    with pytest.raises(RuntimeError, match="Redis inaccessible") as error:
        main_module.on_startup()
    assert "fake-secret-value" not in str(error.value)
