"""Focused regression tests for private deployment and startup safety."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, settings
from app.database import Base
from app.main import app
from app import main as main_module


BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_SIGNING_KEY = "ci-only-signing-key-with-more-than-thirty-two-characters"


def config(**values):
    defaults = {
        "APP_ENV": "test",
        "SECRET_KEY": TEST_SIGNING_KEY,
        "DATABASE_URL": "sqlite:///:memory:",
        "CORS_ORIGINS": "",
        "ALLOW_PUBLIC_REGISTRATION": False,
    }
    defaults.update(values)
    return Settings(_env_file=None, **defaults)


def test_environment_defaults_to_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(_env_file=None).APP_ENV == "production"


@pytest.mark.parametrize("key", [
    "",
    "short",
    "x" * 48,
    "prime-crm-secret-key-change-in-production-please-use-long-random-string",
    "please_generate_a_long_random_secret_key_here_min_32_chars",
])
def test_missing_or_known_unsafe_secret_is_rejected(key):
    with pytest.raises(ValueError, match="SECRET_KEY") as result:
        config(SECRET_KEY=key).validate_runtime()
    if key:
        assert key not in str(result.value)


def test_token_algorithm_cannot_be_weakened():
    with pytest.raises(ValueError, match="HS256"):
        config(ALGORITHM="HS384").validate_runtime()


def test_production_requires_postgres_and_private_registration():
    with pytest.raises(ValueError, match="PostgreSQL"):
        config(APP_ENV="production").validate_runtime()
    with pytest.raises(ValueError, match="Public registration"):
        config(APP_ENV="production", DATABASE_URL="postgresql://ci@localhost/test", ALLOW_PUBLIC_REGISTRATION=True).validate_runtime()
    password = "test-database-password"
    with pytest.raises(ValueError, match="PostgreSQL") as result:
        config(APP_ENV="production", DATABASE_URL=f"postgresql://ci:{password}@/missing-host").validate_runtime()
    assert password not in str(result.value)


@pytest.mark.parametrize("origin", [
    "*",
    "http://app.example.com",
    "https://app.example.com/path",
    "https://user:password@app.example.com",
    "https://app.example.com:bad",
    "https://*.example.com",
])
def test_production_rejects_unsafe_cors_origins(origin):
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        config(APP_ENV="production", DATABASE_URL="postgresql://ci@localhost/test", CORS_ORIGINS=origin).validate_runtime()


def test_explicit_https_origins_or_empty_list_are_accepted_in_production():
    cfg = config(APP_ENV="production", DATABASE_URL="postgresql://ci@localhost/test", CORS_ORIGINS='["https://one.example.com", "https://two.example.com"]')
    cfg.validate_runtime()
    assert cfg.cors_origins_list == ["https://one.example.com", "https://two.example.com"]
    config(APP_ENV="production", DATABASE_URL="postgresql://ci@localhost/test").validate_runtime()


def test_cross_origin_requests_are_restricted():
    client = TestClient(app)
    headers = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}
    allowed = client.options("/api/v1/auth/login-json", headers={**headers, "Origin": "http://localhost:5173"})
    blocked = client.options("/api/v1/auth/login-json", headers={**headers, "Origin": "https://other.example.com"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in allowed.headers
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


def test_public_signup_and_bootstrap_endpoint_are_blocked(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", False)
    client = TestClient(app)
    response = client.post("/api/v1/auth/register", json={
        "email": "person@example.com",
        "password": "test-only-password",
        "first_name": "Test",
        "last_name": "User",
        "company_name": "Example",
    })
    assert response.status_code == 403
    assert client.post("/api/v1/auth/seed-admin").status_code == 404


def test_missing_secret_prevents_import_without_printing_it():
    env = os.environ.copy()
    env.update({
        "APP_ENV": "production",
        "SECRET_KEY": "short-private-test-value",
        "DATABASE_URL": "postgresql://ci@127.0.0.1:1/unused",
        "ALLOW_PUBLIC_REGISTRATION": "false",
        "CORS_ORIGINS": "",
    })
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert env["SECRET_KEY"] not in result.stdout + result.stderr


def isolated_database():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return engine, sessionmaker(bind=engine)


def test_startup_never_creates_tables_when_migrations_are_missing(monkeypatch, tmp_path):
    engine, factory = isolated_database()
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    with pytest.raises(RuntimeError, match="migrations"):
        with TestClient(app):
            pass
    assert inspect(engine).get_table_names() == []
    engine.dispose()


@pytest.mark.parametrize("stale_revision", [None, "older_revision"])
def test_private_startup_rejects_missing_or_stale_migration_revision(monkeypatch, tmp_path, stale_revision):
    engine, factory = isolated_database()
    Base.metadata.create_all(engine)  # Simulate manually created tables without migrations.
    if stale_revision:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": stale_revision})
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    with pytest.raises(RuntimeError, match="migrations"):
        with TestClient(app):
            pass
    # The app must not create or upgrade the Alembic version table.
    with engine.connect() as connection:
        if stale_revision:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == stale_revision
        else:
            assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()


def test_private_startup_refuses_an_empty_user_table(monkeypatch, tmp_path):
    engine, factory = isolated_database()
    Base.metadata.create_all(engine)  # Test-only schema, not the app startup path.
    head = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": head})
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    with pytest.raises(RuntimeError, match="administrateur"):
        with TestClient(app):
            pass
    engine.dispose()
