"""Password policy checks for private and test-only account creation."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bootstrap import bootstrap_first_admin
from app.config import Settings, settings
from app.database import Base, get_db
from app.main import app


ADMIN_PASSWORD = "ci-only-administrator-password"
USER_PASSWORD = "ci-only-new-user-password"


def test_account_password_policy_and_admin_authorization(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    config = Settings(
        _env_file=None,
        APP_ENV="test",
        SECRET_KEY="ci-only-signing-key-with-more-than-thirty-two-characters",
        DATABASE_URL="sqlite:///:memory:",
        CORS_ORIGINS="",
        ALLOW_PUBLIC_REGISTRATION=False,
        FIRST_SUPERUSER_EMAIL="owner@example.com",
        FIRST_SUPERUSER_PASSWORD=ADMIN_PASSWORD,
        FIRST_COMPANY_NAME="Test Company",
    )
    with factory() as db:
        bootstrap_first_admin(db, config)

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", True)
    client = TestClient(app)
    login = client.post("/api/v1/auth/login-json", json={"email": "owner@example.com", "password": ADMIN_PASSWORD})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    payload = {"email": "new@example.com", "first_name": "New", "last_name": "User", "role": "commercial"}

    for invalid in ("short", "x" * 73, "é" * 37, " leading-space-password "):
        response = client.post("/api/v1/users", json={**payload, "password": invalid}, headers=headers)
        assert response.status_code == 400
        assert invalid not in response.text

    invalid_role = client.post("/api/v1/users", json={**payload, "password": USER_PASSWORD, "role": "unknown"}, headers=headers)
    assert invalid_role.status_code == 400
    assert USER_PASSWORD not in invalid_role.text

    created = client.post("/api/v1/users", json={**payload, "password": USER_PASSWORD}, headers=headers)
    assert created.status_code == 200
    assert USER_PASSWORD not in created.text
    user_login = client.post("/api/v1/auth/login-json", json={"email": payload["email"], "password": USER_PASSWORD})
    assert user_login.status_code == 200
    user_headers = {"Authorization": f"Bearer {user_login.json()['access_token']}"}
    forbidden = client.post("/api/v1/users", json={**payload, "email": "other@example.com", "password": USER_PASSWORD}, headers=user_headers)
    assert forbidden.status_code == 403
    assert USER_PASSWORD not in forbidden.text

    # The legacy registration route is available only in test/development and
    # applies the same policy without returning the submitted password.
    registration = client.post("/api/v1/auth/register", json={
        "email": "signup@example.com", "first_name": "Test", "last_name": "User", "password": "short",
    })
    assert registration.status_code == 400
    assert "short" not in registration.text
    engine.dispose()
