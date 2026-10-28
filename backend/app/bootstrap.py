"""Initialize the first administrator explicitly, after Alembic migrations.

Run once before starting the web process. The command is idempotent when users
already exist and never prints the configured email, password or database URL.
"""

import sys
from uuid import uuid4

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import Settings, settings
from .schema import SchemaOutOfDateError, require_current_schema


class BootstrapError(Exception):
    """An expected initialization error whose message contains no secrets."""


def bootstrap_first_admin(db: Session, config: Settings) -> bool:
    """Create the initial company, admin and stages atomically if no users exist.

    Call with a fresh, dedicated session. PostgreSQL's transaction-level advisory
    lock serializes concurrent bootstrap attempts, including during deploys.
    """
    from .core.security import get_password_hash, is_acceptable_new_password
    from .models.company import Company
    from .models.stage import PipelineStage
    from .models.user import User
    from .routers.auth import DEFAULT_STAGES

    with db.begin():
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :version)"), {
                "namespace": 1347571013,
                "version": 1,
            })

        if db.query(User.id).first() is not None:
            return False

        if not config.FIRST_SUPERUSER_EMAIL or not config.FIRST_SUPERUSER_PASSWORD:
            raise BootstrapError("FIRST_SUPERUSER_EMAIL et FIRST_SUPERUSER_PASSWORD sont requis pour le premier administrateur")
        try:
            email = validate_email(config.FIRST_SUPERUSER_EMAIL, check_deliverability=False).normalized
        except EmailNotValidError:
            raise BootstrapError("FIRST_SUPERUSER_EMAIL n'est pas une adresse valide") from None

        password = config.FIRST_SUPERUSER_PASSWORD
        if not is_acceptable_new_password(password):
            raise BootstrapError("FIRST_SUPERUSER_PASSWORD doit contenir au moins 16 caractères et au plus 72 octets, sans espaces aux extrémités")
        company_name = config.FIRST_COMPANY_NAME.strip()
        if not company_name or len(company_name) > 255:
            raise BootstrapError("FIRST_COMPANY_NAME doit contenir entre 1 et 255 caractères")

        company = Company(name=company_name, slug=f"company-{uuid4().hex}", email=email)
        db.add(company)
        db.flush()
        db.add(User(
            email=email,
            hashed_password=get_password_hash(password),
            first_name="Admin",
            last_name="Prime",
            role="admin",
            is_superuser=True,
            company_id=company.id,
        ))
        db.add_all(PipelineStage(company_id=company.id, **stage) for stage in DEFAULT_STAGES)
    return True


def main() -> int:
    try:
        settings.validate_runtime()
    except ValueError:
        print("Configuration invalide : vérifiez APP_ENV, SECRET_KEY, DATABASE_URL et CORS_ORIGINS", file=sys.stderr)
        return 1

    try:
        from .database import SessionLocal

        # Use a separate session: the revision check starts a read transaction,
        # whereas bootstrap_first_admin needs its own atomic transaction.
        with SessionLocal() as db:
            require_current_schema(db)
        with SessionLocal() as db:
            created = bootstrap_first_admin(db, settings)
    except BootstrapError as exc:
        # BootstrapError contains only fixed, sanitized messages.
        print(f"Initialisation refusée : {exc}", file=sys.stderr)
        return 1
    except (SchemaOutOfDateError, SQLAlchemyError):
        print("Initialisation impossible : vérifiez la base et les migrations", file=sys.stderr)
        return 1
    except Exception:
        print("Initialisation impossible : erreur interne", file=sys.stderr)
        return 1

    print("Premier administrateur créé." if created else "Initialisation déjà effectuée ; aucun changement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
