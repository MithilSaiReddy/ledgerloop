import json

from fastapi import APIRouter, Depends, HTTPException, Query
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
    if exc.status != "open":
        raise HTTPException(400, f"exception already {exc.status}")

    resolved_ledger_id = None
    after_payload: dict = {"action": body.action}

    if body.action == "resolved":
        from app.models import LedgerEntry
        from app.pipeline.structure import missing_required_fields

        data = json.loads(exc.extracted_json or "{}")
        data.update(body.edits or {})
        missing = missing_required_fields(data)

        # A human explicitly resolving is the authority signal — we accept the
        # row even with a bad GSTIN/tax mismatch (that's their call to make),
        # but never with missing required fields.
        if missing:
            raise HTTPException(400, f"still missing required fields: {', '.join(missing)}")

        from app.pipeline.reconcile import parse_date

        date = parse_date(data.get("date"))
        if date is None:
            raise HTTPException(400, "date still unparseable")

        entry = LedgerEntry(
            invoice_id=exc.invoice_id,
            owner_id=user.owner_id,
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
            edited_fields=json.dumps(sorted((body.edits or {}).keys())),
        )
        db.add(entry)
        db.flush()
        resolved_ledger_id = entry.id
        exc.resolved_ledger_id = entry.id
        after_payload["ledger_id"] = entry.id
        after_payload["data"] = data

    exc.status = body.action
    db.add(AuditLog(
        actor="dashboard", action="resolve_exception", entity_type="exception",
        owner_id=user.owner_id,
        entity_id=exc.id,
        before_json=json.dumps({"status": "open"}),
        after_json=json.dumps(after_payload),
        note=f"{body.action}: {exc.reason} — {exc.detail}",
    ))
    db.commit()
    return {"ok": True, "status": exc.status, "ledger_id": resolved_ledger_id}
