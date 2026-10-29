"""Regression tests for the initial Alembic migration.

These tests only use a temporary SQLite database or generate PostgreSQL SQL
without a connection. They never connect to an application database.
"""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = BACKEND_DIR / "alembic.ini"
INITIAL_REVISION = "20261028_01"
HEAD_REVISION = "20261029_02"


def run_alembic(working_dir: Path, database_url: str, *arguments: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        cwd=working_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


def test_initial_migration_on_temporary_sqlite_database(tmp_path: Path) -> None:
    # A percent sign in the path verifies ConfigParser URL escaping as well.
    database_file = tmp_path / "schema%test.sqlite"
    database_url = f"sqlite:///{database_file.as_posix()}"

    run_alembic(tmp_path, database_url, "upgrade", "head")
    run_alembic(tmp_path, database_url, "upgrade", "head")  # idempotent
    run_alembic(tmp_path, database_url, "check")

    with sqlite3.connect(database_file) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    assert {"companies", "users", "clients", "opportunities", "quotes"} <= tables
    assert revision == (HEAD_REVISION,)

    # Downgrade is destructive: exercise it only on this disposable test DB.
    run_alembic(tmp_path, database_url, "downgrade", "base")
    with sqlite3.connect(database_file) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "companies" not in tables
    run_alembic(tmp_path, database_url, "upgrade", "head")


def test_session_migration_preserves_existing_users_on_disposable_sqlite(tmp_path: Path) -> None:
    database_file = tmp_path / "existing.sqlite"
    database_url = f"sqlite:///{database_file.as_posix()}"
    run_alembic(tmp_path, database_url, "upgrade", INITIAL_REVISION)
    with sqlite3.connect(database_file) as connection:
        connection.execute("INSERT INTO companies (id, name) VALUES (1, 'Disposable')")
        connection.execute(
            "INSERT INTO users (id, company_id, email, hashed_password, first_name, last_name, is_active) "
            "VALUES (1, 1, 'test@example.test', 'fictitious-hash', 'Test', 'User', 1)"
        )
    run_alembic(tmp_path, database_url, "upgrade", "head")
    run_alembic(tmp_path, database_url, "check")
    with sqlite3.connect(database_file) as connection:
        assert connection.execute("SELECT email, hashed_password, session_nonce FROM users").fetchone() == (
            "test@example.test", "fictitious-hash", None
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD_REVISION,)

    # Only exercise destructive rollback on a throwaway database.
    run_alembic(tmp_path, database_url, "downgrade", INITIAL_REVISION)
    with sqlite3.connect(database_file) as connection:
        assert "session_nonce" not in {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert connection.execute("SELECT email FROM users").fetchone() == ("test@example.test",)


def test_postgres_sql_generation_with_encoded_password(tmp_path: Path) -> None:
    # The address and password are deliberately fictitious. --sql makes no connection.
    database_url = "postgresql://fake:p%40ss@127.0.0.1:1/unused?sslmode=require"
    result = run_alembic(tmp_path, database_url, "upgrade", "head", "--sql")
    assert "CREATE TABLE companies" in result.stdout
    assert "p%40ss" not in result.stdout
    assert "p%40ss" not in result.stderr
