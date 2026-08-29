import datetime as dt
import os
import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings

settings = get_settings()

if settings.is_postgres:
    # We ship psycopg 3; SQLAlchemy needs the explicit dialect name.
    url = settings.supabase_db_url.replace("postgresql://", "postgresql+psycopg://")
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
else:
    # Local dev / tests: SQLite fallback (env DB_PATH honoured).
    _sqlite_path = Path(os.environ.get("DB_PATH", "data/ledgerloop.db"))
    _sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{_sqlite_path}",
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def month_of(date_str: str) -> str:
    return date_str[:7] if len(date_str) >= 7 else ""


GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
