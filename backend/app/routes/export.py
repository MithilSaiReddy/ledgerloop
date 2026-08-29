"""Ledger export: CSV / JSON download for a month.

Bonus feature — kept deliberately simple: generic formats first.
"""

import csv
import io
import json

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.emailer import serialize_ledger
from app.models import Invoice, LedgerEntry

router = APIRouter(prefix="/export", tags=["export"])

CSV_COLUMNS = [
    "date", "type", "vendor", "invoice_no", "gstin",
    "taxable_value", "cgst", "sgst", "igst", "total",
    "category", "source",
]


@router.get("")
def export_ledger(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    format: str = Query("csv", pattern=r"^(csv|json)$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == user.owner_id)
        .filter(LedgerEntry.date.like(f"{month}%"))
        .order_by(LedgerEntry.date, LedgerEntry.id)
        .all()
    )
    sources = {
        inv.id: inv.source
        for inv in db.query(Invoice).filter(Invoice.owner_id == user.owner_id).all()
    }
    rows = []
    for e in entries:
        d = serialize_ledger(e)
        d["source"] = sources.get(e.invoice_id, "telegram")
        rows.append(d)

    filename = f"ledgerloop-{month}"

    if format == "json":
        return Response(
            content=json.dumps(rows, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in CSV_COLUMNS})
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
