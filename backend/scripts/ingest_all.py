"""Ingest every file in data/samples/ through the live pipeline.

Usage:
    PYTHONPATH=backend python scripts/ingest_all.py [--fresh]

--fresh wipes data/ledgerloop.db first so runs are reproducible.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import ExceptionRow, LedgerEntry  # noqa: E402
from app.pipeline.runner import run_pipeline  # noqa: E402


def ingest_samples(owner_id: str, samples_dir: Path,
                   source: str = "eval", verbose: bool = True) -> dict:
    """Run every file in samples_dir through the live pipeline.

    Returns a summary dict of counts. Reusable by the app itself to auto-seed
    a demo database on startup.
    """
    samples = sorted(samples_dir.iterdir())
    if verbose:
        print(f"ingesting {len(samples)} files from {samples_dir} ...\n")

    n_ledger = n_exc = n_fail = 0
    for path in samples:
        db = SessionLocal()
        try:
            res = run_pipeline(db, path, path.name, source=source,
                               telegram_user_id="eval", owner_id=owner_id)
            if verbose:
                mark = {"ledger": "+", "exception": "!", "failed": "x"}[res.status]
                line = f"[{mark}] {path.name}: {res.message}"
                if res.detail:
                    line += f"  ({res.reason}: {res.detail})"
                print(line)
            n_ledger += res.status == "ledger"
            n_exc += res.status == "exception"
            n_fail += res.status == "failed"
        finally:
            db.close()

    return {"ledger": n_ledger, "exceptions": n_exc, "failed": n_fail}


def print_summary(counts: dict) -> None:
    db = SessionLocal()
    months = {}
    for v, d, t in db.query(LedgerEntry.vendor, LedgerEntry.date, LedgerEntry.total).all():
        m = months.setdefault(d[:7], [0, 0.0])
        m[0] += 1
        m[1] += t
    exc_by_reason = {}
    for reason, in db.query(ExceptionRow.reason).all():
        exc_by_reason[reason] = exc_by_reason.get(reason, 0) + 1
    db.close()

    print(f"\nDone: {counts['ledger']} ledger | {counts['exceptions']} exceptions "
          f"| {counts['failed']} failed")
    for month, (count, total) in sorted(months.items()):
        print(f"  ledger {month}: {count} invoices, ₹{total:,.2f}")
    if exc_by_reason:
        print("  exceptions:", ", ".join(f"{k}={v}" for k, v in sorted(exc_by_reason.items())))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    settings = get_settings()

    init_db()
    if args.fresh and not settings.is_postgres:
        # Drop & recreate tables IN PLACE (never unlink the file: a running
        # uvicorn would keep serving the deleted inode). On Postgres, schema
        # is managed by supabase/migrations — pass --fresh only for SQLite.
        from app.db import Base, engine

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        print("dropped + recreated all tables")
    samples_dir = Path(os.environ.get("SAMPLES_DIR", str(ROOT / "data" / "samples")))
    owner_id = os.environ.get("DEMO_OWNER_ID", "") or get_settings().demo_owner_id

    counts = ingest_samples(owner_id, samples_dir)
    print_summary(counts)


if __name__ == "__main__":
    main()
