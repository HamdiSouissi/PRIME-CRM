"""Concurrent session tests on an explicitly disposable local PostgreSQL.

These tests make real commits across independent connections, which is needed
for race testing. They only accept a loopback CI database with an expected name,
create random test accounts, and delete only their own rows in cleanup.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import re
import secrets
import threading

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.core.security import get_password_hash, is_valid_session_nonce
from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.user import User
from app.routers import auth as auth_router
from app.services.redis_store import PASSWORD_CHANGE_ATTEMPTS, get_redis_store
from app.tests.asgi_helpers import WithClientIP


ADMIN_PASSWORD = "fictitious-postgres-admin-password"
OLD_PASSWORD = "fictitious-postgres-old-password"
NEW_PASSWORD = "fictitious-postgres-new-password"


def disposable_postgres_url():
    value = os.environ.get("CI_TEST_POSTGRES_URL", "")
    if not value:
        pytest.skip("CI_TEST_POSTGRES_URL is not set; no PostgreSQL integration database selected")
    try:
        url = make_url(value)
        safe_name = url.database == "primecrm_ci" or bool(re.fullmatch(r"primecrm_sessions_ci_[0-9a-f]{16}", url.database or ""))
        safe = (
            url.drivername in {"postgresql", "postgresql+psycopg2"}
            and url.host == "127.0.0.1"
            and url.port is not None and 1024 <= url.port <= 65535
            and safe_name and not url.query
        )
    except Exception:
        safe = False
    if not safe:
        pytest.fail("CI_TEST_POSTGRES_URL must refer to the disposable, explicitly named local PostgreSQL test database")
    return value


@pytest.fixture
def postgres_harness(monkeypatch):
    engine = create_engine(disposable_postgres_url(), pool_size=8, max_overflow=0)
    factory = sessionmaker(bind=engine, autoflush=False)
    unique = secrets.token_hex(12)
    company_id = None
    clients = []
    try:
        with factory() as db:
            company = Company(name="Disposable Sessions", slug=f"sessions-{unique}")
            db.add(company)
            db.flush()
            admin = User(
                email=f"session-admin-{unique}@example.com", first_name="Test", last_name="Admin",
                company_id=company.id, role="admin", hashed_password=get_password_hash(ADMIN_PASSWORD),
            )
            target = User(
                email=f"session-target-{unique}@example.com", first_name="Test", last_name="Viewer",
                company_id=company.id, role="viewer", hashed_password=get_password_hash(OLD_PASSWORD),
            )
            db.add_all([admin, target])
            db.flush()
            company_id, target_id, admin_email, target_email = company.id, target.id, admin.email, target.email
            db.commit()

        def override_db():
            with factory() as db:
                yield db

        monkeypatch.setattr(settings, "APP_ENV", "test")
        monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
        monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: None)
        app.state.login_ip_guard.reset()

        def new_client():
            client = TestClient(WithClientIP(app, "127.0.0.1"))
            clients.append(client)
            return client

        yield {
            "new_client": new_client, "factory": factory, "company_id": company_id,
            "target_id": target_id, "admin_email": admin_email, "target_email": target_email,
        }
    finally:
        for client in clients:
            client.close()
        if company_id is not None:
            with engine.begin() as connection:
                connection.execute(delete(User).where(User.company_id == company_id))
                connection.execute(delete(Company).where(Company.id == company_id))
            with engine.connect() as connection:
                assert connection.execute(select(Company.id).where(Company.id == company_id)).first() is None
        engine.dispose()


def login(client, email, password):
    return client.post("/api/v1/auth/login-json", json={"email": email, "password": password})


def headers(response):
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize("operation", ["password", "logout", "disable_reenable", "admin_revoke"])
def test_concurrent_login_cannot_gain_new_epoch_after_revocation(postgres_harness, monkeypatch, operation):
    h = postgres_harness
    main, concurrent = h["new_client"](), h["new_client"]()
    target = headers(login(main, h["target_email"], OLD_PASSWORD))
    admin = headers(login(main, h["admin_email"], ADMIN_PASSWORD))
    verified, resume = threading.Event(), threading.Event()
    original_verify = auth_router.verify_password

    def pause_first_old_verification(plain, hashed):
        result = original_verify(plain, hashed)
        if plain == OLD_PASSWORD and not verified.is_set():
            verified.set()
            if not resume.wait(timeout=15):
                raise RuntimeError("Timed out waiting for isolated race test")
        return result

    monkeypatch.setattr(auth_router, "verify_password", pause_first_old_verification)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(login, concurrent, h["target_email"], OLD_PASSWORD)
        try:
            assert verified.wait(timeout=15)
            if operation == "password":
                result = main.post("/api/v1/auth/change-password", headers=target, json={
                    "old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
                })
            elif operation == "logout":
                result = main.post("/api/v1/auth/logout-all", headers=target)
            elif operation == "admin_revoke":
                result = main.post(f"/api/v1/users/{h['target_id']}/revoke-sessions", headers=admin)
            else:
                result = main.put(f"/api/v1/users/{h['target_id']}", headers=admin, json={"is_active": False})
                assert result.status_code == 200
                result = main.put(f"/api/v1/users/{h['target_id']}", headers=admin, json={"is_active": True})
            assert result.status_code == 200, result.text
        finally:
            resume.set()
        stale_login = pending.result(timeout=15)
    assert stale_login.status_code == 409
    assert "access_token" not in stale_login.text and OLD_PASSWORD not in stale_login.text
    assert main.get("/api/v1/auth/me", headers=target).status_code == 401
    assert main.get("/api/v1/auth/me", headers=admin).status_code == 200
    password = NEW_PASSWORD if operation == "password" else OLD_PASSWORD
    assert main.get("/api/v1/auth/me", headers=headers(login(main, h["target_email"], password))).status_code == 200
    if operation == "password":
        assert login(main, h["target_email"], OLD_PASSWORD).status_code == 401


@pytest.mark.parametrize("operation", ["password", "logout"])
def test_revocation_after_login_commit_still_rejects_late_issued_token(postgres_harness, monkeypatch, operation):
    h = postgres_harness
    main, concurrent = h["new_client"](), h["new_client"]()
    target = headers(login(main, h["target_email"], OLD_PASSWORD))
    committed, resume = threading.Event(), threading.Event()
    original_create = auth_router.create_access_token

    def pause_first_target_token(subject, *, session_nonce, **kwargs):
        if subject == h["target_id"] and not committed.is_set():
            committed.set()
            if not resume.wait(timeout=15):
                raise RuntimeError("Timed out waiting for isolated token issuance test")
        return original_create(subject, session_nonce=session_nonce, **kwargs)

    monkeypatch.setattr(auth_router, "create_access_token", pause_first_target_token)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(login, concurrent, h["target_email"], OLD_PASSWORD)
        try:
            assert committed.wait(timeout=15)
            if operation == "password":
                result = main.post("/api/v1/auth/change-password", headers=target, json={
                    "old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
                })
            else:
                result = main.post("/api/v1/auth/logout-all", headers=target)
            assert result.status_code == 200, result.text
        finally:
            resume.set()
        late_token = headers(pending.result(timeout=15))
    assert main.get("/api/v1/auth/me", headers=late_token).status_code == 401
    new_password = NEW_PASSWORD if operation == "password" else OLD_PASSWORD
    assert main.get("/api/v1/auth/me", headers=headers(login(main, h["target_email"], new_password))).status_code == 200


def test_two_first_logins_initialize_legacy_epoch_atomically(postgres_harness, monkeypatch):
    h = postgres_harness
    with h["factory"]() as db:
        db.execute(update(User).where(User.id == h["target_id"]).values(session_nonce=None))
        db.commit()
    first, second = h["new_client"](), h["new_client"]()
    barrier = threading.Barrier(2)
    original_verify = auth_router.verify_password

    def synchronized_verify(plain, hashed):
        result = original_verify(plain, hashed)
        if plain == OLD_PASSWORD:
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(auth_router, "verify_password", synchronized_verify)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(login, client, h["target_email"], OLD_PASSWORD) for client in (first, second)]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(response for response in responses if response.status_code == 200)
    assert first.get("/api/v1/auth/me", headers=headers(accepted)).status_code == 200
    with h["factory"]() as db:
        assert is_valid_session_nonce(db.get(User, h["target_id"]).session_nonce)


def test_postgres_sessions_and_separate_redis_limiter_work_together(postgres_harness, redis_store, monkeypatch):
    h = postgres_harness
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: redis_store)
    client = h["new_client"]()
    target = headers(login(client, h["target_email"], OLD_PASSWORD))
    for _ in range(PASSWORD_CHANGE_ATTEMPTS):
        response = client.post("/api/v1/auth/change-password", headers=target, json={
            "old_password": "fictitious-wrong-password", "new_password": NEW_PASSWORD,
        })
        assert response.status_code == 400
    blocked = client.post("/api/v1/auth/change-password", headers=target, json={
        "old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
    })
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert client.post("/api/v1/auth/logout-all", headers=target).status_code == 200
    assert client.get("/api/v1/auth/me", headers=target).status_code == 401
    # The distinct login counter still permits a new session.
    fresh = headers(login(client, h["target_email"], OLD_PASSWORD))
    assert client.get("/api/v1/auth/me", headers=fresh).status_code == 200


def test_concurrent_password_changes_have_only_one_winner(postgres_harness, monkeypatch):
    h = postgres_harness
    first, second = h["new_client"](), h["new_client"]()
    original = headers(login(first, h["target_email"], OLD_PASSWORD))
    passwords = ["fictitious-first-new-password", "fictitious-second-new-password"]
    barrier = threading.Barrier(2)
    original_hash = auth_router.get_password_hash

    def synchronized_hash(password):
        result = original_hash(password)
        if password in passwords:
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(auth_router, "get_password_hash", synchronized_hash)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(client.post, "/api/v1/auth/change-password", headers=original, json={
                "old_password": OLD_PASSWORD, "new_password": password,
            })
            for client, password in zip((first, second), passwords)
        ]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 401]
    assert first.get("/api/v1/auth/me", headers=original).status_code == 401
    assert login(first, h["target_email"], OLD_PASSWORD).status_code == 401
    statuses = [login(first, h["target_email"], password).status_code for password in passwords]
    assert sorted(statuses) == [200, 401]
    assert all(password not in response.text for password in passwords for response in responses)
