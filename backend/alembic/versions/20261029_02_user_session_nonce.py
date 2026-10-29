"""Add a per-user session revocation epoch.

Revision ID: 20261029_02
Revises: 20261028_01

Existing rows intentionally start with NULL: old JWTs are rejected and each
user receives a random epoch on their next successful login. New accounts get a
random value from the application. No credential is printed or migrated.
"""

from alembic import op
import sqlalchemy as sa


revision = "20261029_02"
down_revision = "20261028_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_nonce", sa.String(length=43), nullable=True))


def downgrade() -> None:
    # Rolling back the application as well can re-enable revoked JWTs; see
    # docs/security.md before considering a downgrade outside a disposable DB.
    op.drop_column("users", "session_nonce")
