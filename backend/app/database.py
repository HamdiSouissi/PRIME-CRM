from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from .config import settings

# Handle SQLite vs PostgreSQL
connect_args = {}
engine_kwargs = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    if ":memory:" in settings.DATABASE_URL:
        engine_kwargs["poolclass"] = StaticPool

try:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        **engine_kwargs
    )
except Exception:
    # Invalid URLs can contain credentials; never include them in startup errors.
    raise RuntimeError("DATABASE_URL invalide ou pilote de base indisponible") from None

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
