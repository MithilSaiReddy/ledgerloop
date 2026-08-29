import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.emailer import send_month_end
from app.models import AuditLog

router = APIRouter(tags=["month-end", "audit"])


@router.post("/month-end/send")
def month_end_send(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return send_month_end(db, month, user)


@router.get("/month-end/preview")
def month_end_preview(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.emailer import build_month_bundle, render_html

    bundle = build_month_bundle(db, month, user.owner_id)
    return {"bundle": bundle, "html": render_html(bundle)}


@router.get("/audit")
def get_audit(
    limit: int = 200,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.owner_id == user.owner_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "before": json.loads(r.before_json) if r.before_json else None,
            "after": json.loads(r.after_json) if r.after_json else None,
            "note": r.note,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
