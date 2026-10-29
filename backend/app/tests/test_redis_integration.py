"""Real Redis integration tests; only an explicitly selected local test server."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import select
import socket
import socketserver
import ssl
import threading
import time
from urllib.parse import urlsplit

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import verify_redis
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.services.redis_store import (
    CACHE_SECONDS,
    IP_LOGIN_ATTEMPTS,
    IP_LOGIN_WINDOW_SECONDS,
    LOGIN_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
    PASSWORD_CHANGE_ATTEMPTS,
    PASSWORD_CHANGE_WINDOW_SECONDS,
    LoginRateLimited,
    RedisStore,
    create_redis_store,
    get_redis_store,
)
from app.tests.asgi_helpers import WithClientIP


TEST_KEY = "test-only-signing-key-with-more-than-32-characters"
TEST_PASSWORD = "test-only-user-password-9827"


@pytest.fixture
def api(redis_store, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: redis_store)
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", True)
    app.state.login_ip_guard.reset()
    client = TestClient(WithClientIP(app, "127.0.0.1"))

    def register(email, company):
        response = client.post("/api/v1/auth/register", json={
            "email": email,
            "password": TEST_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "company_name": company,
        })
        assert response.status_code == 200, response.text
        data = response.json()
        return {"Authorization": "Bearer " + data["access_token"]}, data["user"]["company_id"]

    first = register("first@example.com", "Tenant One")
    second = register("second@example.com", "Tenant Two")
    yield client, first, second
    engine.dispose()


def test_encrypted_cache_tenant_isolation_and_invalidation(redis_store, api):
    client, (headers_a, company_a), (headers_b, company_b) = api
    assert client.get("/api/v1/dashboard", headers=headers_a).status_code == 200
    assert client.get("/api/v1/dashboard", headers=headers_b).status_code == 200
    key_a = redis_store._stage_key(company_a)
    key_b = redis_store._stage_key(company_b)
    assert key_a != key_b
    encrypted_a = redis_store.client.get(key_a)
    assert encrypted_a and '"company_id"' not in encrypted_a and '"won"' not in encrypted_a
    assert "first@example.com" not in key_a + encrypted_a
    assert 0 < redis_store.client.ttl(key_a) <= CACHE_SECONDS
    outcomes_a = redis_store.get_stage_outcomes(company_a)
    outcomes_b = redis_store.get_stage_outcomes(company_b)
    assert outcomes_a and outcomes_b and outcomes_a != outcomes_b

    # Replaying one tenant's encrypted value under another key is rejected.
    redis_store.client.set(key_b, encrypted_a, ex=CACHE_SECONDS)
    assert redis_store.get_stage_outcomes(company_b) is None
    assert client.get("/api/v1/dashboard", headers=headers_b).status_code == 200
    assert redis_store.get_stage_outcomes(company_b) == outcomes_b

    created = client.post("/api/v1/stages", headers=headers_a, json={"name": "Test won", "is_won": True})
    assert created.status_code == 200
    stage_id = created.json()["id"]
    assert redis_store.client.get(key_a) is None
    assert redis_store.get_stage_outcomes(company_b) == outcomes_b
    assert client.get("/api/v1/dashboard", headers=headers_a).status_code == 200
    assert stage_id in redis_store.get_stage_outcomes(company_a)[0]

    changed = client.put(f"/api/v1/stages/{stage_id}", headers=headers_a, json={"is_won": False, "is_lost": True})
    assert changed.status_code == 200
    assert redis_store.client.get(key_a) is None
    assert client.get("/api/v1/dashboard", headers=headers_a).status_code == 200
    won, lost = redis_store.get_stage_outcomes(company_a)
    assert stage_id not in won and stage_id in lost

    assert client.delete(f"/api/v1/stages/{stage_id}", headers=headers_a).status_code == 200
    assert redis_store.client.get(key_a) is None
    assert client.get("/api/v1/dashboard", headers=headers_a).status_code == 200
    assert stage_id not in redis_store.get_stage_outcomes(company_a)[1]
    assert client.get("/api/v1/dashboard").status_code == 401
    assert client.get("/api/v1/admin/health").status_code == 401
    assert client.get("/api/v1/admin/health", headers=headers_a).status_code == 200


def test_invalid_or_expired_ciphertext_is_a_cache_miss(redis_store):
    company_id = 123
    key = redis_store._stage_key(company_id)
    redis_store.client.set(key, "not-a-fernet-token", ex=CACHE_SECONDS)
    assert redis_store.get_stage_outcomes(company_id) is None
    old = json.dumps({"company_id": company_id, "won": [1], "lost": [2]}).encode()
    token = redis_store._cipher.encrypt_at_time(old, int(time.time()) - CACHE_SECONDS - 2)
    redis_store.client.set(key, token, ex=CACHE_SECONDS)
    assert redis_store.get_stage_outcomes(company_id) is None


def test_rate_limit_is_atomic_across_concurrent_calls_and_repairs_ttl(redis_store):
    email = "Mixed.Case@example.com"

    def attempt(_):
        try:
            redis_store.record_login(email)
            return True
        except LoginRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=20) as workers:
        results = list(workers.map(attempt, range(30)))
    assert sum(results) == LOGIN_ATTEMPTS
    key = redis_store._login_key(email)
    assert email not in key
    assert redis_store._login_key(email.lower()) == key
    assert 0 < redis_store.client.ttl(key) <= LOGIN_WINDOW_SECONDS
    assert int(redis_store.client.get(key)) == 30

    no_ttl_key = redis_store._login_key("no-ttl@example.com")
    redis_store.client.set(no_ttl_key, "1")
    assert redis_store.client.ttl(no_ttl_key) == -1
    redis_store.record_login("no-ttl@example.com")
    assert 0 < redis_store.client.ttl(no_ttl_key) <= LOGIN_WINDOW_SECONDS


def test_ip_rate_limit_is_atomic_shared_and_pseudonymized(redis_store):
    client_ip = "192.0.2.84"  # Documentation address, never contacted.
    other_worker = RedisStore(redis_store.client, TEST_KEY, redis_store.prefix)

    def attempt(number):
        try:
            (redis_store if number % 2 else other_worker).record_login_ip(client_ip)
            return True
        except LoginRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=20) as workers:
        results = list(workers.map(attempt, range(50)))
    assert sum(results) == IP_LOGIN_ATTEMPTS
    key = redis_store._login_ip_key(client_ip)
    assert client_ip not in key
    assert redis_store._login_ip_key("::ffff:192.0.2.84") == key
    assert redis_store._login_ip_key("2001:db8::1") == redis_store._login_ip_key("2001:0db8:0:0:0:0:0:1")
    assert 0 < redis_store.client.ttl(key) <= IP_LOGIN_WINDOW_SECONDS
    assert int(redis_store.client.get(key)) == 50
    redis_store.record_login_ip("192.0.2.85")


def test_real_redis_ip_limit_covers_both_routes_before_body_validation(redis_store, api):
    client, _, _ = api
    for number in range(IP_LOGIN_ATTEMPTS):
        if number % 2:
            response = client.post("/api/v1/auth/login", data={})
        else:
            response = client.post("/api/v1/auth/login-json", json={})
        assert response.status_code == 422
    blocked = client.post("/api/v1/auth/login-json", json={})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    key = redis_store._login_ip_key("127.0.0.1")
    assert int(redis_store.client.get(key)) == IP_LOGIN_ATTEMPTS + 1
    assert list(redis_store.client.scan_iter(match=f"{redis_store.prefix}:login:*")) == []
    for _ in range(70):
        assert client.post("/api/v1/auth/login-json", json={}).status_code == 429
    assert int(redis_store.client.get(key)) == IP_LOGIN_ATTEMPTS + 1  # Local denial cache skipped Redis.
    other = TestClient(WithClientIP(app, "127.0.0.2"))
    try:
        assert other.post("/api/v1/auth/login-json", json={}).status_code == 422
    finally:
        other.close()


def test_both_login_routes_share_a_limit_and_other_accounts_are_unaffected(redis_store, api):
    client, _, _ = api
    email = "unknown@example.com"
    for index in range(LOGIN_ATTEMPTS):
        if index % 2:
            response = client.post("/api/v1/auth/login", data={"username": email, "password": "incorrect"})
        else:
            response = client.post("/api/v1/auth/login-json", json={"email": email, "password": "incorrect"})
        assert response.status_code == 401
    blocked = client.post("/api/v1/auth/login-json", json={"email": email.upper(), "password": "incorrect"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert email not in blocked.text
    other = client.post("/api/v1/auth/login-json", json={"email": "other@example.com", "password": "incorrect"})
    assert other.status_code == 401
    keys = list(redis_store.client.scan_iter(match=f"{redis_store.prefix}:login:*"))
    assert len(keys) == 2
    assert all("@" not in key and "incorrect" not in key for key in keys)


def test_password_change_limiter_is_atomic_for_concurrent_attempts(redis_store):
    def attempt(_):
        try:
            redis_store.record_password_change("parallel@example.com")
            return True
        except LoginRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=12) as workers:
        results = list(workers.map(attempt, range(20)))
    assert sum(results) == PASSWORD_CHANGE_ATTEMPTS
    key = redis_store._password_change_key("parallel@example.com")
    assert int(redis_store.client.get(key)) == 20
    assert 0 < redis_store.client.ttl(key) <= PASSWORD_CHANGE_WINDOW_SECONDS


def test_password_change_limit_is_separate_and_pseudonymized(redis_store, api):
    client, (headers, _), (other_headers, _) = api
    wrong_password = "fictitious-wrong-password"
    new_password = "fictitious-new-password-4827"
    for _ in range(PASSWORD_CHANGE_ATTEMPTS):
        response = client.post("/api/v1/auth/change-password", headers=headers, json={
            "old_password": wrong_password, "new_password": new_password,
        })
        assert response.status_code == 400
        assert wrong_password not in response.text and new_password not in response.text
    blocked = client.post("/api/v1/auth/change-password", headers=headers, json={
        "old_password": TEST_PASSWORD, "new_password": new_password,
    })
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    key = redis_store._password_change_key("first@example.com")
    assert key != redis_store._login_key("first@example.com")
    assert "first@example.com" not in key and TEST_PASSWORD not in key
    assert int(redis_store.client.get(key)) == PASSWORD_CHANGE_ATTEMPTS + 1
    assert 0 < redis_store.client.ttl(key) <= PASSWORD_CHANGE_WINDOW_SECONDS
    # Neither a fresh login for this account nor another user's counter is blocked.
    assert client.post("/api/v1/auth/login-json", json={"email": "first@example.com", "password": TEST_PASSWORD}).status_code == 200
    # Successful logins also consume the pre-validation IP counter.
    assert int(redis_store.client.get(redis_store._login_ip_key("127.0.0.1"))) == 1
    assert client.post("/api/v1/auth/change-password", headers=other_headers, json={
        "old_password": wrong_password, "new_password": new_password,
    }).status_code == 400
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_cache_falls_back_to_database_but_login_fails_closed_on_outage(redis_store, api, monkeypatch):
    client, (headers, _), _ = api
    broken = create_redis_store("redis://127.0.0.1:1/0", TEST_KEY, prefix=redis_store.prefix)
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: broken)
    assert client.get("/api/v1/dashboard", headers=headers).status_code == 200
    login = client.post("/api/v1/auth/login-json", json={"email": "first@example.com", "password": TEST_PASSWORD})
    assert login.status_code == 503
    assert TEST_PASSWORD not in login.text and "127.0.0.1" not in login.text
    change = client.post("/api/v1/auth/change-password", headers=headers, json={
        "old_password": TEST_PASSWORD, "new_password": "fictitious-new-password-4827",
    })
    assert change.status_code == 503
    assert TEST_PASSWORD not in change.text and "127.0.0.1" not in change.text
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    broken.close()


class _TlsProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with self.server.tls_context.wrap_socket(self.request, server_side=True) as incoming:
                with socket.create_connection(("127.0.0.1", self.server.redis_port), timeout=3) as upstream:
                    while True:
                        ready, _, _ = select.select([incoming, upstream], [], [], 3)
                        if not ready:
                            break
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            (upstream if source is incoming else incoming).sendall(data)
        except (OSError, ssl.SSLError):
            pass


def _test_tls_material(tmp_path: Path) -> tuple[Path, Path, Path]:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable Test CA")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_file, cert_file, key_file = (tmp_path / "ca.pem", tmp_path / "cert.pem", tmp_path / "key.pem")
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca_file, cert_file, key_file


def test_tls_diagnostic_detects_real_trust_and_hostname_failures(redis_store, tmp_path, monkeypatch, capsys):
    ca_file, cert_file, key_file = _test_tls_material(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    proxy = _TlsProxy(("127.0.0.1", 0), _ProxyHandler)
    proxy.tls_context = context
    proxy.redis_port = urlsplit(os.environ["CI_TEST_REDIS_URL"]).port
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    port = proxy.server_address[1]
    try:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("SSL_CERT_DIR", raising=False)
        assert verify_redis.diagnose_tls(("localhost", port)) == 1
        untrusted = capsys.readouterr().out
        assert "RESULTAT_TLS=ECHEC_CERTIFICAT" in untrusted
        assert "fake-secret" not in untrusted and "localhost" not in untrusted

        monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
        assert verify_redis.diagnose_tls(("localhost", port)) == 0
        trusted = capsys.readouterr().out
        assert "RESULTAT_TLS=SUCCES" in trusted
        assert "fake-secret" not in trusted and str(ca_file) not in trusted

        assert verify_redis.diagnose_tls(("127.0.0.1", port)) == 1
        mismatch = capsys.readouterr().out
        assert "RESULTAT_TLS=ECHEC_CERTIFICAT" in mismatch
        assert "CATEGORIE_TLS=ADRESSE_IP_INCORRECTE" in mismatch
        assert "fake-secret" not in mismatch and "127.0.0.1" not in mismatch
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=3)


def test_tls_verifies_the_server_hostname(redis_store, tmp_path, monkeypatch):
    ca_file, cert_file, key_file = _test_tls_material(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    proxy = _TlsProxy(("127.0.0.1", 0), _ProxyHandler)
    proxy.tls_context = context
    proxy.redis_port = urlsplit(os.environ["CI_TEST_REDIS_URL"]).port
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    # Even though the OS trusts our test CA, certifi's real bundle does not.
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
    port = proxy.server_address[1]
    untrusted = good = bad = None
    try:
        untrusted = create_redis_store(f"rediss://localhost:{port}/0", TEST_KEY, redis_store.prefix)
        with pytest.raises(RedisError):
            untrusted.client.ping()

        # Only the test's isolated certifi bundle contains the disposable CA.
        monkeypatch.setattr(certifi, "where", lambda: str(ca_file))
        good = create_redis_store(f"rediss://localhost:{port}/0", TEST_KEY, redis_store.prefix)
        bad = create_redis_store(f"rediss://127.0.0.1:{port}/0", TEST_KEY, redis_store.prefix)
        assert good.client.ping() is True
        # The CA is trusted, but 127.0.0.1 does not match the localhost-only SAN.
        with pytest.raises(RedisError):
            bad.client.ping()
    finally:
        for store in (untrusted, good, bad):
            if store is not None:
                store.close()
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=3)
