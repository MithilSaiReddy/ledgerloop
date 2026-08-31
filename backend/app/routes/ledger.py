import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.emailer import serialize_ledger
from app.models import AuditLog, ExceptionRow, Invoice, LedgerEntry

router = APIRouter(prefix="/ledger", tags=["ledger"])

EDITABLE_FIELDS = {"vendor", "gstin", "invoice_no", "date", "taxable_value",
                   "cgst", "sgst", "igst", "total", "category",
                   "hsn_code", "place_of_supply"}


class LedgerEdit(BaseModel):
    field: str
    value: str | int | float | None


def month_query(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")) -> str:
    return month


@router.get("/months")
def get_months(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Per-month summaries powering the home 'Monthly records' cards:
    money in (sales) / out (purchases), net, GST, open exception count."""
    from collections import defaultdict

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == user.owner_id)
        .all()
    )
    exc_counts: dict[str, int] = defaultdict(int)
    for status, month, _ in (
        db.query(ExceptionRow.status, ExceptionRow.month, ExceptionRow.id)
        .filter(ExceptionRow.owner_id == user.owner_id, ExceptionRow.status == "open")
        .all()
    ):
        if status == "open" and month:
            exc_counts[month] += 1

    months: dict[str, dict] = {}
    for e in entries:
        m = e.date[:7]
        s = months.setdefault(m, {
            "month": m, "count": 0, "purchases": 0, "sales": 0,
            "money_in": 0.0, "money_out": 0.0, "net": 0.0,
            "gst": 0.0, "taxable_value": 0.0, "total": 0.0,
            "exceptions": 0,
        })
        s["count"] += 1
        gst = round((e.cgst or 0) + (e.sgst or 0) + (e.igst or 0), 2)
        s["gst"] = round(s["gst"] + gst, 2)
        s["taxable_value"] = round(s["taxable_value"] + (e.taxable_value or 0), 2)
        s["total"] = round(s["total"] + (e.total or 0), 2)
        if e.type == "sale":
            s["sales"] += 1
            s["money_in"] = round(s["money_in"] + (e.total or 0), 2)
            s["net"] = round(s["net"] + (e.total or 0), 2)
        elif e.type == "purchase":
            s["purchases"] += 1
            s["money_out"] = round(s["money_out"] + (e.total or 0), 2)
            s["net"] = round(s["net"] - (e.total or 0), 2)
        # legacy rows without a type stay counted but unclassified

    for m, s in months.items():
        s["exceptions"] = exc_counts.get(m, 0)

    return sorted(months.values(), key=lambda s: s["month"], reverse=True)


@router.get("")
def get_ledger(
    month: str = Depends(month_query),
    type: str | None = Query(None, pattern=r"^(purchase|sale|all)$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    query = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == user.owner_id)
        .filter(LedgerEntry.date.like(f"{month}%"))
    )
    if type and type != "all":
        query = query.filter(LedgerEntry.type == type)
    entries = query.order_by(LedgerEntry.date, LedgerEntry.id).all()
    sources = {
        inv.id: inv.source
        for inv in db.query(Invoice).filter(Invoice.owner_id == user.owner_id).all()
    }
    out = []
    for e in entries:
        d = serialize_ledger(e)
        d["source"] = sources.get(e.invoice_id, "telegram")
        out.append(d)
    return out


@router.patch("/{entry_id}")
def edit_ledger_entry(
    entry_id: int,
    edit: LedgerEdit,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if edit.field not in EDITABLE_FIELDS:
        raise HTTPException(400, f"field {edit.field!r} is not editable")

    entry = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.id == entry_id, LedgerEntry.owner_id == user.owner_id)
        .first()
    )
    if entry is None:
        raise HTTPException(404, "ledger entry not found")

    before = serialize_ledger(entry)
    old_value = getattr(entry, edit.field)

    coerced: object = edit.value
    if edit.field in ("taxable_value", "cgst", "sgst", "igst", "total"):
        try:
            coerced = round(float(edit.value), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, f"field {edit.field} must be numeric")
    elif edit.field == "gstin" and edit.value:
        from app.db import GSTIN_RE

        coerced = str(edit.value).strip().upper()

    setattr(entry, edit.field, coerced)

    touched = json.loads(entry.edited_fields)
    if edit.field not in touched:
        touched.append(edit.field)
        entry.edited_fields = json.dumps(touched)

    after = serialize_ledger(entry)
    db.add(AuditLog(
        actor="dashboard", action="edit_ledger", entity_type="ledger",
        owner_id=user.owner_id,
        entity_id=entry.id,
        before_json=json.dumps({edit.field: old_value}),
        after_json=json.dumps({edit.field: coerced}),
        note=f"edited {edit.field}",
    ))
    db.commit()
    return {"ok": True, "entry": after}


@router.post("/{entry_id}/recheck")
def recheck_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Re-run reconciliation checks on the (possibly human-edited) row."""
    from app.gstin import gstin_valid
    from app.pipeline.reconcile import check_tax_sum

    entry = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.id == entry_id, LedgerEntry.owner_id == user.owner_id)
        .first()
    )
    if entry is None:
        raise HTTPException(404, "ledger entry not found")
    data = serialize_ledger(entry)
    return {
        "tax_sum_ok": check_tax_sum(data),
        "gstin_ok": gstin_valid(entry.gstin),
    }


# --- Telegram-authenticated variant (chat-id -> owner via user_settings) ---

telegram_router = APIRouter(prefix="/telegram", tags=["telegram"])


def _telegram_owner(db: Session, telegram_user_id: str | None) -> str:
    from app.routes.invoices import _owner_for_telegram

    return _owner_for_telegram(db, telegram_user_id)


def _latest_month_with_data(db: Session, owner_id: str) -> str:
    row = (
        db.query(LedgerEntry.date)
        .filter(LedgerEntry.owner_id == owner_id)
        .order_by(LedgerEntry.date.desc())
        .first()
    )
    return row[0][:7] if row else None


@telegram_router.get("/ledger")
def telegram_get_ledger(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    telegram_user_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Compact per-month summary for the /ledger bot command.

    Totals-only shape (the bot renders a short chat-friendly message): count,
    purchases/sales split, money in/out, net, GST and open exceptions, plus a
    resolved `month` (the requested one, or the latest month with data).
    """
    from collections import defaultdict

    owner_id = _telegram_owner(db, telegram_user_id)
    if not month:
        month = _latest_month_with_data(db, owner_id)

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == owner_id)
        .filter(LedgerEntry.date.like(f"{month}%"))
        .all()
    )
    exc_counts: dict[str, int] = defaultdict(int)
    for status, m in (
        db.query(ExceptionRow.status, ExceptionRow.month)
        .filter(ExceptionRow.owner_id == owner_id, ExceptionRow.status == "open")
        .all()
    ):
        if status == "open" and m:
            exc_counts[m] += 1

    purchases = sales = 0
    money_in = money_out = gst = taxable = total = 0.0
    for e in entries:
        gst += (e.cgst or 0) + (e.sgst or 0) + (e.igst or 0)
        taxable += e.taxable_value or 0
        total += e.total or 0
        if e.type == "sale":
            sales += 1
            money_in += e.total or 0
        elif e.type == "purchase":
            purchases += 1
            money_out += e.total or 0

    return {
        "month": month,
        "count": len(entries),
        "purchases": purchases,
        "sales": sales,
        "money_in": round(money_in, 2),
        "money_out": round(money_out, 2),
        "net": round(money_in - money_out, 2),
        "gst": round(gst, 2),
        "taxable_value": round(taxable, 2),
        "total": round(total, 2),
        "open_exceptions": exc_counts.get(month, 0),
    }
