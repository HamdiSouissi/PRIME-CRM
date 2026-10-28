"""First-admin bootstrap tests using only disposable in-memory SQLite."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bootstrap import BootstrapError, bootstrap_first_admin
from app.config import Settings, settings
from app.core.security import verify_password
from app.database import Base
from app.models.company import Company
from app.models.stage import PipelineStage
from app.models.user import User


TEST_PASSWORD = "only-a-test-password-4827"


def bootstrap_config(**values):
    defaults = {
        "APP_ENV": "test",
        "SECRET_KEY": "ci-only-signing-key-with-more-than-thirty-two-characters",
        "DATABASE_URL": "sqlite:///:memory:",
        "CORS_ORIGINS": "",
        "ALLOW_PUBLIC_REGISTRATION": False,
        "FIRST_SUPERUSER_EMAIL": "owner@example.com",
        "FIRST_SUPERUSER_PASSWORD": TEST_PASSWORD,
        "FIRST_COMPANY_NAME": "Example company",
    }
    defaults.update(values)
    return Settings(_env_file=None, **defaults)


@pytest.fixture
def factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def test_bootstrap_is_atomic_idempotent_and_never_stores_plaintext(factory, capsys, caplog):
    with factory() as db:
        assert bootstrap_first_admin(db, bootstrap_config()) is True
    with factory() as db:
        users = db.query(User).all()
        assert len(users) == 1
        assert users[0].email == "owner@example.com"
        assert users[0].role == "admin" and users[0].is_superuser is True
        assert users[0].hashed_password != TEST_PASSWORD
        assert verify_password(TEST_PASSWORD, users[0].hashed_password)
        assert db.query(Company).count() == 1
        assert db.query(PipelineStage).count() == 8

    # Existing users make subsequent startup independent of bootstrap secrets.
    with factory() as db:
        assert bootstrap_first_admin(db, bootstrap_config(FIRST_SUPERUSER_EMAIL="", FIRST_SUPERUSER_PASSWORD="")) is False
    with factory() as db:
        assert db.query(User).count() == 1
        assert db.query(Company).count() == 1
        assert db.query(PipelineStage).count() == 8

    captured = capsys.readouterr()
    assert TEST_PASSWORD not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("changes", [
    {"FIRST_SUPERUSER_EMAIL": ""},
    {"FIRST_SUPERUSER_PASSWORD": ""},
    {"FIRST_SUPERUSER_EMAIL": "not-an-address"},
    {"FIRST_SUPERUSER_PASSWORD": "too-short"},
    {"FIRST_SUPERUSER_PASSWORD": "p" * 73},
    {"FIRST_SUPERUSER_PASSWORD": " long-enough-password "},
    {"FIRST_COMPANY_NAME": "  "},
])
def test_invalid_bootstrap_configuration_leaves_the_database_empty(factory, changes):
    with factory() as db:
        with pytest.raises(BootstrapError) as result:
            bootstrap_first_admin(db, bootstrap_config(**changes))
        for value in changes.values():
            if value and value.strip():
                assert value not in str(result.value)
    with factory() as db:
        assert db.query(User).count() == 0
        assert db.query(Company).count() == 0
        assert db.query(PipelineStage).count() == 0


def test_app_starts_after_explicit_bootstrap(factory, monkeypatch, tmp_path, capsys):
    from fastapi.testclient import TestClient
    from app import main as main_module

    with factory() as db:
        bootstrap_first_admin(db, bootstrap_config())
        # This unit fixture uses create_all; mark its test-only revision. The
        # CLI integration test separately runs actual Alembic migrations.
        config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
        head = ScriptDirectory.from_config(Config(str(config_path))).get_current_head()
        db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        db.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": head})
        db.commit()
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    with TestClient(main_module.app) as client:
        assert client.get("/health").json()["status"] == "ok"
    captured = capsys.readouterr()
    assert TEST_PASSWORD not in captured.out + captured.err
