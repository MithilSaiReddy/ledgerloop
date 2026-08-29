import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import AuditLog, UserSettings

router = APIRouter(prefix="/user-settings", tags=["user-settings"])


class SettingsBody(BaseModel):
    shop_name: str = ""
    ca_email: str
    gstin: str | None = None
    state: str | None = None
    state_code: str | None = None
    address: str | None = None
    gst_registered: bool = False
    telegram_chat_id: str | None = None


def _serialize(row: UserSettings) -> dict:
    return {
        "owner_id": row.owner_id,
        "shop_name": row.shop_name,
        "ca_email": row.ca_email,
        "gstin": row.gstin,
        "state": row.state,
        "state_code": row.state_code,
        "address": row.address,
        "gst_registered": row.gst_registered,
        "telegram_chat_id": row.telegram_chat_id,
    }


@router.get("/me")
def get_my_settings(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    row = db.get(UserSettings, user.owner_id)
    if row is None:
        raise HTTPException(404, "No settings yet — complete onboarding first")
    return _serialize(row)


class GoogleTokensBody(BaseModel):
    access_token: str
    refresh_token: str | None = None


@router.post("/google-tokens")
def save_google_tokens(
    body: GoogleTokensBody,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Store the owner's Google OAuth tokens (from the Supabase session) so
    month-end emails can be sent via the Gmail API on their behalf.
    Google only returns a refresh token on first consent — keep the old one
    when the new session omits it."""
    row = db.get(UserSettings, user.owner_id)
    if row is None:
        raise HTTPException(404, "Complete onboarding first")
    row.google_access_token = body.access_token
    if body.refresh_token:
        row.google_refresh_token = body.refresh_token
    db.commit()
    return {"ok": True, "has_refresh": bool(row.google_refresh_token)}


@router.post("")
def save_my_settings(
    body: SettingsBody,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Upsert: creates the row during onboarding, updates it from Settings."""
    ca_email = body.ca_email.strip().lower()
    if "@" not in ca_email or "." not in ca_email.split("@")[-1]:
        raise HTTPException(400, "Please enter a valid CA email address")

    row = db.get(UserSettings, user.owner_id)
    created = row is None
    if created:
        row = UserSettings(owner_id=user.owner_id)
        db.add(row)

    before = _serialize(row) if not created else None
    row.shop_name = body.shop_name.strip()
    row.ca_email = ca_email
    row.gstin = (body.gstin or "").strip().upper() or None
    row.state = (body.state or "").strip() or None
    row.state_code = (body.state_code or "").strip().zfill(2) or None
    row.address = (body.address or "").strip() or None
    row.gst_registered = bool(body.gst_registered)
    row.telegram_chat_id = (body.telegram_chat_id or "").strip() or None

    db.add(AuditLog(
        actor="dashboard", action="update_settings", entity_type="settings",
        owner_id=user.owner_id,
        before_json=json.dumps(before) if before else None,
        after_json=json.dumps(_serialize(row)),
        note="onboarding" if created else "updated settings",
    ))
    db.commit()
    return {"ok": True, "created": created, "settings": _serialize(row)}
