"""Password and session security using only disposable SQLite databases."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from jose import jwt
import pytest
from redis.exceptions import RedisError
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.security import create_access_token, get_password_hash, is_valid_session_nonce, verify_password
from app.database import Base, get_db
from app.main import app
from app.models.company import Company
from app.models.user import User
from app.services.redis_store import get_redis_store


OLD_PASSWORD = "test-old-password-please-change"
NEW_PASSWORD = "test-new-password-please-change"
WRONG_PASSWORD = "fictitious-incorrect-password"


@pytest.fixture
def harness(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        first, second = Company(name="First", slug="first"), Company(name="Second", slug="second")
        db.add_all([first, second])
        db.flush()
        shared_test_hash = get_password_hash(OLD_PASSWORD)
        users = [
            User(email="admin@example.com", first_name="A", last_name="Admin", role="admin", company_id=first.id, hashed_password=shared_test_hash),
            User(email="viewer@example.com", first_name="B", last_name="Viewer", role="viewer", company_id=first.id, hashed_password=shared_test_hash),
            User(email="other@example.com", first_name="C", last_name="Other", role="admin", company_id=second.id, hashed_password=shared_test_hash),
        ]
        db.add_all(users)
        db.flush()
        ids = [user.id for user in users]
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: None)
    client = TestClient(app)
    yield {"client": client, "factory": factory, "ids": ids}
    client.close()
    engine.dispose()


def login(client, email="admin@example.com", password=OLD_PASSWORD, *, form=False):
    if form:
        return client.post("/api/v1/auth/login", data={"username": email, "password": password})
    return client.post("/api/v1/auth/login-json", json={"email": email, "password": password})


def auth(response):
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def me(client, headers):
    return client.get("/api/v1/auth/me", headers=headers)


@pytest.mark.parametrize("form", [False, True])
def test_password_change_invalidates_all_own_tokens_but_not_other_users(harness, form):
    client = harness["client"]
    first = auth(login(client, form=form))
    second = auth(login(client, form=not form))
    other = auth(login(client, "viewer@example.com"))
    assert first != second  # Each issuance has its own random JWT ID.

    wrong = client.post("/api/v1/auth/change-password", headers=first, json={"old_password": WRONG_PASSWORD, "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400
    assert WRONG_PASSWORD not in wrong.text and NEW_PASSWORD not in wrong.text
    assert me(client, first).status_code == me(client, second).status_code == 200

    for invalid in ("short", "x" * 73, "é" * 37, " leading-and-trailing ", OLD_PASSWORD):
        response = client.post("/api/v1/auth/change-password", headers=first, json={"old_password": OLD_PASSWORD, "new_password": invalid})
        assert response.status_code == 400
        assert OLD_PASSWORD not in response.text and invalid not in response.text
        assert me(client, first).status_code == 200

    changed = client.post("/api/v1/auth/change-password", headers=first, json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD})
    assert changed.status_code == 200
    assert OLD_PASSWORD not in changed.text and NEW_PASSWORD not in changed.text
    assert me(client, first).status_code == me(client, second).status_code == 401
    assert me(client, other).status_code == 200
    assert login(client).status_code == 401
    fresh = auth(login(client, password=NEW_PASSWORD))
    assert me(client, fresh).status_code == 200
    with harness["factory"]() as db:
        user = db.get(User, harness["ids"][0])
        assert user.hashed_password != NEW_PASSWORD
        assert verify_password(NEW_PASSWORD, user.hashed_password)


def test_viewer_can_change_own_password_without_admin_access(harness):
    client = harness["client"]
    viewer = auth(login(client, "viewer@example.com"))
    assert client.get("/api/v1/admin/health", headers=viewer).status_code == 403
    changed = client.post("/api/v1/auth/change-password", headers=viewer, json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD})
    assert changed.status_code == 200
    assert me(client, viewer).status_code == 401
    assert me(client, auth(login(client, "viewer@example.com", NEW_PASSWORD))).status_code == 200
    assert client.post("/api/v1/auth/change-password", json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD}).status_code == 401


def test_authentication_responses_are_not_cacheable(harness):
    client = harness["client"]
    result = login(client)
    assert result.headers["Cache-Control"] == "no-store"
    current = me(client, auth(result))
    assert current.headers["Cache-Control"] == "no-store"
    invalid = login(client, password=WRONG_PASSWORD)
    assert invalid.headers["Cache-Control"] == "no-store"


def test_logout_is_server_side_and_global_for_only_that_account(harness):
    client = harness["client"]
    first, second = auth(login(client)), auth(login(client))
    other = auth(login(client, "viewer@example.com"))
    assert client.post("/api/v1/auth/logout-all", headers=first).status_code == 200
    assert me(client, first).status_code == me(client, second).status_code == 401
    assert client.post("/api/v1/auth/logout-all", headers=second).status_code == 401
    assert me(client, other).status_code == 200
    assert me(client, auth(login(client))).status_code == 200
    assert client.post("/api/v1/auth/logout-all").status_code == 401


def test_admin_revocation_is_authorized_and_scoped_to_the_company(harness):
    client = harness["client"]
    admin = auth(login(client))
    viewer = auth(login(client, "viewer@example.com"))
    other = auth(login(client, "other@example.com"))
    admin_id, viewer_id, other_id = harness["ids"]
    assert client.post(f"/api/v1/users/{admin_id}/revoke-sessions", headers=viewer).status_code == 403
    assert client.post(f"/api/v1/users/{other_id}/revoke-sessions", headers=admin).status_code == 404
    assert client.post("/api/v1/users/999999/revoke-sessions", headers=admin).status_code == 404
    assert me(client, viewer).status_code == me(client, other).status_code == 200
    assert client.post(f"/api/v1/users/{viewer_id}/revoke-sessions", headers=admin).status_code == 200
    assert me(client, viewer).status_code == 401
    assert me(client, admin).status_code == me(client, other).status_code == 200
    assert me(client, auth(login(client, "viewer@example.com"))).status_code == 200
    # The API also allows an admin to revoke its own sessions, even though the
    # UI offers the dedicated "logout everywhere" action instead.
    assert client.post(f"/api/v1/users/{admin_id}/revoke-sessions", headers=admin).status_code == 200
    assert me(client, admin).status_code == 401
    assert me(client, other).status_code == 200


def test_disabling_reenabling_and_changing_role_never_revives_old_tokens(harness):
    client = harness["client"]
    admin = auth(login(client))
    viewer = auth(login(client, "viewer@example.com"))
    viewer_id = harness["ids"][1]
    assert client.put(f"/api/v1/users/{viewer_id}", headers=admin, json={"is_active": False}).status_code == 200
    assert me(client, viewer).status_code == 401
    assert login(client, "viewer@example.com").status_code == 401
    assert client.put(f"/api/v1/users/{viewer_id}", headers=admin, json={"is_active": True}).status_code == 200
    assert me(client, viewer).status_code == 401
    fresh = auth(login(client, "viewer@example.com"))
    assert client.put(f"/api/v1/users/{viewer_id}", headers=admin, json={"role": "manager"}).status_code == 200
    assert me(client, fresh).status_code == 401
    assert me(client, auth(login(client, "viewer@example.com"))).status_code == 200
    assert client.put(f"/api/v1/users/{viewer_id}", headers=admin, json={"role": "invalid"}).status_code == 400
    assert client.put(f"/api/v1/users/{viewer_id}", headers=admin, json={"role": "super_admin"}).status_code == 400
    assert client.put(f"/api/v1/users/{viewer_id}", headers=admin, json={"is_active": None}).status_code == 400


def test_migrated_account_requires_new_login_and_initializes_its_epoch(harness):
    client, factory = harness["client"], harness["factory"]
    user_id = harness["ids"][0]
    with factory() as db:
        db.execute(update(User).where(User.id == user_id).values(session_nonce=None))
        db.commit()
    legacy = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert me(client, {"Authorization": f"Bearer {legacy}"}).status_code == 401
    fresh = auth(login(client))
    assert me(client, fresh).status_code == 200
    with factory() as db:
        assert is_valid_session_nonce(db.get(User, user_id).session_nonce)


def test_deleted_and_recreated_user_cannot_reuse_predecessor_tokens(harness):
    client, factory = harness["client"], harness["factory"]
    old = auth(login(client, "viewer@example.com"))
    user_id = harness["ids"][1]
    with factory() as db:
        user = db.get(User, user_id)
        company_id, old_nonce, password_hash = user.company_id, user.session_nonce, user.hashed_password
        db.delete(user)
        db.commit()
        replacement = User(id=user_id, company_id=company_id, email="viewer@example.com", first_name="New", last_name="Viewer", role="viewer", hashed_password=password_hash)
        db.add(replacement)
        db.commit()
        assert replacement.session_nonce != old_nonce
    assert me(client, old).status_code == 401
    assert me(client, auth(login(client, "viewer@example.com"))).status_code == 200


def test_expired_legacy_and_malformed_signed_tokens_are_rejected(harness):
    client, factory = harness["client"], harness["factory"]
    user_id = harness["ids"][0]
    with factory() as db:
        nonce = db.get(User, user_id).session_nonce
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"sub": str(user_id), "sid": nonce, "jti": "A" * 32, "iat": now, "exp": now + 3600}
    variants = [
        {k: v for k, v in claims.items() if k != "sid"},
        {k: v for k, v in claims.items() if k != "exp"},
        {k: v for k, v in claims.items() if k != "jti"},
        {**claims, "sid": None},
        {**claims, "sub": "9" * 100},
        {**claims, "sub": []},
        {**claims, "exp": None},
        {**claims, "iat": []},
        {**claims, "jti": []},
    ]
    for variant in variants:
        token = jwt.encode(variant, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        assert me(client, {"Authorization": f"Bearer {token}"}).status_code == 401
    expired = create_access_token(user_id, session_nonce=nonce, expires_delta=timedelta(seconds=-1))
    assert me(client, {"Authorization": f"Bearer {expired}"}).status_code == 401
    assert me(client, {"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_validation_errors_never_echo_passwords(harness):
    client = harness["client"]
    headers = auth(login(client))
    responses = [
        client.post("/api/v1/auth/change-password", headers=headers, json={"old_password": OLD_PASSWORD}),
        client.post("/api/v1/auth/login-json", json={"email": "invalid", "password": OLD_PASSWORD}),
        client.post("/api/v1/auth/login", data={"password": OLD_PASSWORD}),
        client.post("/api/v1/auth/register", json={"password": OLD_PASSWORD}),
        client.post("/api/v1/users", headers=headers, json={"password": OLD_PASSWORD}),
    ]
    for response in responses:
        assert response.status_code == 422
        assert OLD_PASSWORD not in response.text
    assert me(client, headers).status_code == 200


def test_change_fails_closed_on_redis_error_without_revoking_or_leaking(harness, monkeypatch):
    client = harness["client"]
    headers = auth(login(client))

    class BrokenStore:
        def record_password_change(self, identifier):
            raise RedisError("fictitious-redis-secret")

    monkeypatch.setitem(app.dependency_overrides, get_redis_store, lambda: BrokenStore())
    response = client.post("/api/v1/auth/change-password", headers=headers, json={"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD})
    assert response.status_code == 503
    assert "fictitious-redis-secret" not in response.text
    assert OLD_PASSWORD not in response.text and NEW_PASSWORD not in response.text
    assert me(client, headers).status_code == 200
    with harness["factory"]() as db:
        assert verify_password(OLD_PASSWORD, db.get(User, harness["ids"][0]).hashed_password)


def test_bcrypt_never_accepts_a_longer_password_by_truncation():
    hashed = get_password_hash("x" * 72)
    assert verify_password("x" * 72, hashed)
    assert not verify_password("x" * 73, hashed)
    assert not verify_password("é" * 37, hashed)
