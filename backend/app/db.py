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
        # pgBouncer (Supabase pooler) can't reuse server-side prepared
        # statements cleanly — identical queries collide with
        # `DuplicatePreparedStatement`. Run plain, client-side only.
        connect_args={"prepare_threshold": None},
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
    _sqlite_add_missing_columns()


def _sqlite_add_missing_columns() -> None:
    """SQLite (local dev demo) can't add columns via create_all on an existing
    DB file. Patch the new columns in defensively so old demo DBs keep working.
    Postgres gets these from supabase/migrations instead."""
    if settings.is_postgres:
        return
    from sqlalchemy import text

    # (table, new column, sqlite column def)
    patches = [
        ("ledger", "tax_note", "text"),
        ("user_settings", "tax_rates", "text"),
    ]
    with engine.begin() as conn:
        for table, col, ddl in patches:
            has = any(row[1] == col for row in conn.execute(text(f"pragma table_info({table})")))
            if not has:
                conn.execute(text(f"alter table {table} add column {col} {ddl}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
