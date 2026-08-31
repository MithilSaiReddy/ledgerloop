"""Recompute auto-derived GST on existing ledger rows recorded with ₹0 tax.

New bills already get CGST/SGST/IGST derived at inges time (see
app/pipeline/reconcile.apply_tax_fallback). Rows filed < THIS version were stored
with whatever the extractor read — often ₹0 because the bill printed no split.
This script re-runs the same derivation over those historical rows.

Usage:
    PYTHONPATH=backend python scripts/backfill_taxes.py [--owner <owner_id>] \
        [--dry-run]

--dry-run prints what would change without writing.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import AuditLog, LedgerEntry, UserSettings  # noqa: E402
from app.pipeline.reconcile import apply_tax_fallback  # noqa: E402


def _owner_context(db, owner_id: str) -> dict:
    row = db.get(UserSettings, owner_id)
    if row is None:
        return {}
    tax_rates = None
    if row.tax_rates:
        try:
            parsed = json.loads(row.tax_rates)
            tax_rates = parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            tax_rates = None
    return {
        "state_code": row.state_code,
        "gst_registered": row.gst_registered,
        "tax_rates": tax_rates,
        "_has_settings": True,
    }


def backfill(owner_id: str | None = None, dry_run: bool = False) -> int:
    init_db()
    db = SessionLocal()
    try:
        q = db.query(LedgerEntry).filter(
            LedgerEntry.cgst == 0, LedgerEntry.sgst == 0, LedgerEntry.igst == 0
        )
        if owner_id:
            q = q.filter(LedgerEntry.owner_id == owner_id)

        updated = 0
        for e in q.all():
            inv = {
                "type": e.type,
                "category": e.category,
                "taxable_value": e.taxable_value,
                "cgst": e.cgst,
                "sgst": e.sgst,
                "igst": e.igst,
                "total": e.total,
                "place_of_supply": e.place_of_supply or "",
            }
            out, note = apply_tax_fallback(inv, _owner_context(db, e.owner_id))
            changed = (
                note is not None
                and (
                    round(float(out.get("cgst") or 0), 2) != round(e.cgst, 2)
                    or round(float(out.get("sgst") or 0), 2) != round(e.sgst, 2)
                    or round(float(out.get("igst") or 0), 2) != round(e.igst, 2)
                    or round(float(out.get("taxable_value") or 0), 2) != round(e.taxable_value, 2)
                )
            )
            if not changed:
                continue

            before = {"cgst": e.cgst, "sgst": e.sgst, "igst": e.igst,
                      "taxable_value": e.taxable_value}
            after = {k: out.get(k) for k in ("cgst", "sgst", "igst", "taxable_value")}
            print(f"[{'dry-run' if dry_run else 'update'}] #{e.id} "
                  f"{e.vendor} {e.invoice_no} → tax_note={note!r}")
            updated += 1

            if not dry_run:
                e.cgst = round(float(out["cgst"] or 0), 2)
                e.sgst = round(float(out["sgst"] or 0), 2)
                e.igst = round(float(out["igst"] or 0), 2)
                e.taxable_value = round(float(out["taxable_value"]), 2)
                e.tax_note = note
                db.add(AuditLog(
                    actor="system", action="recompute_tax", entity_type="ledger",
                    owner_id=e.owner_id, entity_id=e.id,
                    before_json=json.dumps(before), after_json=json.dumps(after),
                    note=note,
                ))

        if not dry_run:
            db.commit()
        print(f"\n{updated} rows {'would be' if dry_run else 'updated'}.")
        return updated
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner", help="restrict to one owner_id")
    ap.add_argument("--dry-run", action="store_true",
                    help="print changes without writing")
    args = ap.parse_args()
    backfill(args.owner, dry_run=args.dry_run)