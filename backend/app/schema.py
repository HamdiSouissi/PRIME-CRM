"""Verify that the database is at the migration heads without mutating it."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session


class SchemaOutOfDateError(Exception):
    """The database is not at the revisions expected by this application."""


def require_current_schema(db: Session) -> None:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    expected_heads = set(ScriptDirectory.from_config(Config(str(config_path))).get_heads())
    actual_heads = set(MigrationContext.configure(db.connection()).get_current_heads())
    if not expected_heads or expected_heads != actual_heads:
        raise SchemaOutOfDateError("Les migrations de la base ne sont pas à jour")
