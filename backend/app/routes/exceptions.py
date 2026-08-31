import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import AuditLog, ExceptionRow, Invoice

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.get("")
def get_exceptions(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    status: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    q = (
        db.query(ExceptionRow, Invoice.filename)
        .join(Invoice, ExceptionRow.invoice_id == Invoice.id)
        .filter(ExceptionRow.owner_id == user.owner_id)
        .filter(or_(ExceptionRow.month == month, ExceptionRow.month == ""))
        .order_by(ExceptionRow.created_at.desc())
    )
    if status:
        q = q.filter(ExceptionRow.status == status)
    return [
        {
            "id": x.id,
            "invoice_id": x.invoice_id,
            "filename": fname,
            "reason": x.reason,
            "detail": x.detail,
            "status": x.status,
            "extracted": json.loads(x.extracted_json) if x.extracted_json else None,
            "created_at": x.created_at.isoformat(),
        }
        for x, fname in q.all()
    ]


class ResolveBody(BaseModel):
    action: str  # 'resolved' (push to ledger) or 'dismissed'
    edits: dict | None = None  # optional corrected fields before pushing


def _owner_gst_context(db: Session, owner_id: str) -> dict:
    """The owner's GST profile (state, registration, rate overrides) needed by
    the auto-derive step when a row is pushed to the ledger by hand."""
    from app.models import UserSettings

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
    }


def _resolve_exception(db: Session, exc: ExceptionRow, owner_id: str,
                       action: str, edits: dict | None, actor: str) -> dict:
    """Shared resolve core: push an open exception to the ledger (resolved) or
    drop it (dismissed), leaving an audit trail. Used by both the dashboard
    (Supabase JWT) and the Telegram bot (chat-id auth)."""
    if exc.status != "open":
        raise HTTPException(400, f"exception already {exc.status}")

    resolved_ledger_id = None
    after_payload: dict = {"action": action}

    if action == "resolved":
        from app.models import LedgerEntry
        from app.pipeline.structure import missing_required_fields, normalize_extraction

        data = json.loads(exc.extracted_json or "{}")
        data.update(edits or {})
        data = normalize_extraction(data)
        missing = missing_required_fields(data)

        # A human explicitly resolving is the authority signal — we accept the
        # row even with a bad GSTIN/tax mismatch (that's their call to make),
        # but never with missing required fields.
        if missing:
            raise HTTPException(400, f"still missing required fields: {', '.join(missing)}")

        from app.pipeline.reconcile import apply_tax_fallback, parse_date

        date = parse_date(data.get("date"))
        if date is None:
            raise HTTPException(400, "date still unparseable")

        # Same tax fill-in as the automatic path: an approved no-tax sale still
        # gets CGST/SGST derived from the lump total (owner GST context applied).
        derived, tax_note = apply_tax_fallback(data, _owner_gst_context(db, owner_id))
        data = derived

        entry = LedgerEntry(
            invoice_id=exc.invoice_id,
            owner_id=owner_id,
            type=(data.get("type") if data.get("type") in ("purchase", "sale") else None),
            vendor=data["vendor"],
            gstin=(data.get("gstin") or "").strip().upper() or None,
            invoice_no=str(data["invoice_no"]),
            date=date,
            taxable_value=float(data["taxable_value"]),
            cgst=float(data.get("cgst") or 0),
            sgst=float(data.get("sgst") or 0),
            igst=float(data.get("igst") or 0),
            total=float(data["total"]),
            category=data.get("category") or "uncategorized",
            tax_note=tax_note,
            items=json.dumps(data.get("items") or [], ensure_ascii=False),
            edited_fields=json.dumps(sorted((edits or {}).keys())),
        )
        db.add(entry)
        db.flush()
        resolved_ledger_id = entry.id
        exc.resolved_ledger_id = entry.id
        after_payload["ledger_id"] = entry.id
        after_payload["data"] = data

    exc.status = action
    db.add(AuditLog(
        actor=actor, action="resolve_exception", entity_type="exception",
        owner_id=owner_id,
        entity_id=exc.id,
        before_json=json.dumps({"status": "open"}),
        after_json=json.dumps(after_payload),
        note=f"{action}: {exc.reason} — {exc.detail}",
    ))
    db.commit()
    return {"ok": True, "status": exc.status, "ledger_id": resolved_ledger_id}


@router.post("/{exception_id}/resolve")
def resolve_exception(
    exception_id: int,
    body: ResolveBody,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if body.action not in ("resolved", "dismissed"):
        raise HTTPException(400, "action must be 'resolved' or 'dismissed'")

    exc = (
        db.query(ExceptionRow)
        .filter(ExceptionRow.id == exception_id, ExceptionRow.owner_id == user.owner_id)
        .first()
    )
    if exc is None:
        raise HTTPException(404, "exception not found")
    return _resolve_exception(db, exc, user.owner_id, body.action, body.edits, actor="dashboard")


# --- Telegram-authenticated variants (chat-id -> owner via user_settings) ---

telegram_router = APIRouter(prefix="/telegram", tags=["telegram"])


def _telegram_owner(db: Session, telegram_user_id: str | None) -> str:
    from app.routes.invoices import _owner_for_telegram

    return _owner_for_telegram(db, telegram_user_id)


def _get_owned_exception(db: Session, exception_id: int, owner_id: str) -> ExceptionRow:
    exc = (
        db.query(ExceptionRow)
        .filter(ExceptionRow.id == exception_id, ExceptionRow.owner_id == owner_id)
        .first()
    )
    if exc is None:
        raise HTTPException(404, "exception not found")
    return exc


@telegram_router.get("/exceptions/{exception_id}")
def telegram_get_exception(
    exception_id: int,
    telegram_user_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Full details of one exception for the bot's View button."""
    owner_id = _telegram_owner(db, telegram_user_id)
    exc = _get_owned_exception(db, exception_id, owner_id)
    return {
        "id": exc.id,
        "invoice_id": exc.invoice_id,
        "reason": exc.reason,
        "detail": exc.detail,
        "status": exc.status,
        "extracted": json.loads(exc.extracted_json) if exc.extracted_json else None,
        "month": exc.month,
    }


@telegram_router.post("/exceptions/{exception_id}/resolve")
def telegram_resolve_exception(
    exception_id: int,
    telegram_user_id: str | None = Form(None),
    action: str = Form("resolved"),
    db: Session = Depends(get_db),
):
    action = action.lower()
    if action not in ("resolved", "dismissed"):
        raise HTTPException(400, "action must be 'resolved' or 'dismissed'")
    owner_id = _telegram_owner(db, telegram_user_id)
    exc = _get_owned_exception(db, exception_id, owner_id)
    return _resolve_exception(db, exc, owner_id, action, None, actor="telegram")


@telegram_router.get("/audit")
def telegram_get_audit(
    limit: int = 20,
    telegram_user_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Recent audit activity for the /audit bot command."""
    owner_id = _telegram_owner(db, telegram_user_id)
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.owner_id == owner_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(min(limit, 50))
        .all()
    )
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "note": r.note,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
