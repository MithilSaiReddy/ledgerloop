"""Ledger export for the CA: India-standard purchase and sales registers.

One row per bill (invoice), no line items — matching the formats the GST
ecosystem expects (GSTR-2B reconciliation for purchases, GSTR-1 B2B for
sales). The JSON download keeps the full per-bill detail for backup.

`purchase_register_csv` / `sales_register_csv` are shared by the download
endpoint and the month-end CA email so both always carry the same files.
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

# GSTIN of supplier | supplier name | invoice number | date | value | taxes
PURCHASE_COLUMNS = [
    "GSTIN of Supplier", "Supplier Name", "Invoice Number", "Invoice Date",
    "Invoice Value", "Taxable Value", "CGST", "SGST", "IGST",
]

# GSTR-1 B2B style register for sales.
SALES_COLUMNS = [
    "GSTIN of Recipient", "Customer Name", "Invoice Number", "Invoice Date",
    "Place of Supply", "Invoice Value", "Taxable Value", "CGST", "SGST", "IGST",
]


def _fmt_date(d: str) -> str:
    """YYYY-MM-DD -> DD-MM-YYYY (Indian standard, reads cleanly in Excel)."""
    parts = (d or "").split("-")
    if len(parts) == 3 and len(parts[0]) == 4 and parts[0].isdigit():
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return d or ""


def _register_rows(db: Session, month: str, owner_id: str, db_type: str) -> list[dict]:
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == owner_id)
        .filter(LedgerEntry.type == db_type)
        .filter(LedgerEntry.date.like(f"{month}%"))
        .order_by(LedgerEntry.date, LedgerEntry.id)
        .all()
    )
    return [serialize_ledger(e) for e in entries]


def _to_csv(columns: list[str], rows: list[dict], build) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        row = build(r)
        writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})
    return buf.getvalue()


def purchase_register_csv(db: Session, month: str, owner_id: str) -> str:
    """Purchase register (GSTR-2B/ITC style), one row per bill."""
    rows = _register_rows(db, month, owner_id, "purchase")

    def build(d: dict) -> dict:
        return {
            "GSTIN of Supplier": d.get("gstin") or "",
            "Supplier Name": d.get("party_name") or d["vendor"],
            "Invoice Number": d["invoice_no"],
            "Invoice Date": _fmt_date(d["date"]),
            "Invoice Value": d["total"],
            "Taxable Value": d["taxable_value"],
            "CGST": d["cgst"],
            "SGST": d["sgst"],
            "IGST": d["igst"],
        }

    return _to_csv(PURCHASE_COLUMNS, rows, build)


def sales_register_csv(db: Session, month: str, owner_id: str) -> str:
    """Sales register (GSTR-1 B2B style), one row per bill."""
    rows = _register_rows(db, month, owner_id, "sale")

    def build(d: dict) -> dict:
        return {
            "GSTIN of Recipient": d.get("gstin") or "",
            "Customer Name": d.get("party_name") or d["vendor"],
            "Invoice Number": d["invoice_no"],
            "Invoice Date": _fmt_date(d["date"]),
            "Place of Supply": d.get("place_of_supply") or (
                "Inter-State" if d.get("is_interstate") else ""
            ),
            "Invoice Value": d["total"],
            "Taxable Value": d["taxable_value"],
            "CGST": d["cgst"],
            "SGST": d["sgst"],
            "IGST": d["igst"],
        }

    return _to_csv(SALES_COLUMNS, rows, build)


@router.get("")
def export_ledger(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    format: str = Query("csv", pattern=r"^(csv|json)$"),
    type: str = Query("all", pattern=r"^(all|purchase|sales)$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if format == "json":
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
        return Response(
            content=json.dumps(rows, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    if type == "purchase":
        body = purchase_register_csv(db, month, user.owner_id)
        filename = f"purchases-{month}"
    elif type == "sales":
        body = sales_register_csv(db, month, user.owner_id)
        filename = f"sales-{month}"
    else:
        # Combined fallback (not used by the UI): one row per bill.
        body = _combined_csv(db, month, user.owner_id)
        filename = f"ledgerloop-{month}"

    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


def _combined_csv(db: Session, month: str, owner_id: str) -> str:
    columns = [
        "Date", "Type", "Party", "Bill No", "GSTIN", "Taxable Value",
        "CGST", "SGST", "IGST", "Total", "Category", "Source",
    ]
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == owner_id)
        .filter(LedgerEntry.date.like(f"{month}%"))
        .order_by(LedgerEntry.date, LedgerEntry.id)
        .all()
    )
    sources = {
        inv.id: inv.source
        for inv in db.query(Invoice).filter(Invoice.owner_id == owner_id).all()
    }

    def build(d: dict) -> dict:
        return {
            "Date": _fmt_date(d["date"]),
            "Type": "Purchase" if d["type"] == "purchase" else "Sale",
            "Party": d.get("party_name") or d["vendor"],
            "Bill No": d["invoice_no"],
            "GSTIN": d.get("gstin") or "",
            "Taxable Value": d["taxable_value"],
            "CGST": d["cgst"],
            "SGST": d["sgst"],
            "IGST": d["igst"],
            "Total": d["total"],
            "Category": d["category"],
            "Source": sources.get(d.get("invoice_id"), "telegram"),
        }

    rows = []
    for e in entries:
        rows.append(serialize_ledger(e))
    return _to_csv(columns, rows, build)