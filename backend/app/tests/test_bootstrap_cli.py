"""Exercise the real migration, bootstrap and login on a temporary SQLite DB."""

import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = BACKEND_DIR / "alembic.ini"


def run(command, cwd, env):
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=30, check=True)


def test_cli_refuses_unmigrated_database_without_creating_tables(tmp_path):
    database_file = tmp_path / "unmigrated.sqlite"
    password = "test-only-password-" + secrets.token_urlsafe(8)
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(BACKEND_DIR),
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{database_file.as_posix()}",
        "REDIS_URL": "",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "CORS_ORIGINS": "",
        "ALLOW_PUBLIC_REGISTRATION": "false",
        "FIRST_SUPERUSER_EMAIL": "owner@example.com",
        "FIRST_SUPERUSER_PASSWORD": password,
        "FIRST_COMPANY_NAME": "Test Company",
    })
    result = subprocess.run([sys.executable, "-m", "app.bootstrap"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "migrations" in result.stderr
    assert password not in result.stdout + result.stderr
    with sqlite3.connect(database_file) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall() == []


def test_cli_bootstrap_after_migration_and_private_login(tmp_path):
    database_file = tmp_path / "private-crm.sqlite"
    password = "test-only-password-" + secrets.token_urlsafe(8)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update({
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{database_file.as_posix()}",
        "REDIS_URL": "",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "CORS_ORIGINS": "http://localhost:5173",
        "ALLOW_PUBLIC_REGISTRATION": "false",
        "FIRST_SUPERUSER_EMAIL": "owner@example.com",
        "FIRST_SUPERUSER_PASSWORD": password,
        "FIRST_COMPANY_NAME": "Test Company",
        "UPLOAD_DIR": str(tmp_path / "uploads"),
    })

    # Run from a temporary directory to avoid reading a developer's .env.
    run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "upgrade", "head"], tmp_path, env)
    # Import the app from the repository while keeping the working directory
    # temporary, so a developer's backend/.env is never read by this test.
    env["PYTHONPATH"] = str(BACKEND_DIR)
    first = run([sys.executable, "-m", "app.bootstrap"], tmp_path, env)
    assert "Premier administrateur créé" in first.stdout
    assert password not in first.stdout + first.stderr

    with sqlite3.connect(database_file) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM pipeline_stages").fetchone() == (8,)
        assert db.execute("SELECT hashed_password FROM users").fetchone()[0] != password

    # Credentials are no longer needed once the first account exists.
    env.pop("FIRST_SUPERUSER_EMAIL")
    env.pop("FIRST_SUPERUSER_PASSWORD")
    again = run([sys.executable, "-m", "app.bootstrap"], tmp_path, env)
    assert "aucun changement" in again.stdout

    # Pass the test password separately; no real credential is used or logged.
    env["CI_LOGIN_PASSWORD"] = password
    script = """
import os
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    result = client.post('/api/v1/auth/login-json', json={
        'email': 'owner@example.com', 'password': os.environ['CI_LOGIN_PASSWORD'],
    })
    assert result.status_code == 200
    token = result.json()['access_token']
    assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    assert client.post('/api/v1/auth/seed-admin').status_code == 404
    blocked = client.post('/api/v1/auth/register', json={
        'email': 'other@example.com', 'password': 'test-only-password',
        'first_name': 'Other', 'last_name': 'User',
    })
    assert blocked.status_code == 403
print('private login ok')
"""
    result = run([sys.executable, "-c", script], tmp_path, env)
    assert "private login ok" in result.stdout
    assert password not in result.stdout + result.stderr
