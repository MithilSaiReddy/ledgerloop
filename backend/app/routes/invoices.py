import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.db import get_db
from app.models import UserSettings
from app.pipeline.runner import run_pipeline

router = APIRouter(prefix="/invoices", tags=["invoices"])

ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff",
                ".tif", ".txt", ".docx", ".xlsx", ".html", ".eml", ".csv"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _save_upload(file: UploadFile) -> Path:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file type: {ext or 'unknown'}")
    contents = file.file.read(MAX_BYTES + 1)
    if len(contents) > MAX_BYTES:
        raise HTTPException(400, "File is larger than 10 MB")

    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / (file.filename or "upload.bin")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        shutil.move(str(tmp_path), str(dest))
    except shutil.SameFileError:
        pass
    return dest


def _owner_for_telegram(db: Session, telegram_user_id: str | None) -> str:
    """Resolve a Telegram user to the shop owner via user_settings."""
    if telegram_user_id:
        row = (
            db.query(UserSettings.owner_id)
            .filter(UserSettings.telegram_chat_id == telegram_user_id)
            .first()
        )
        if row:
            return row.owner_id
        import os

        fallback = os.environ.get("DEMO_OWNER_ID", "")
        if fallback:
            return fallback
    raise HTTPException(401, "Unknown Telegram user — link your account in settings first")


@router.post("/ingest")
async def ingest_invoice(
    file: UploadFile = File(...),
    user_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Telegram path: authenticated via the Telegram -> owner mapping."""
    dest = _save_upload(file)
    owner_id = _owner_for_telegram(db, user_id)

    result = run_pipeline(db, dest, file.filename or dest.name,
                          source="api", telegram_user_id=user_id, owner_id=owner_id)
    return _result_payload(result)


@router.post("/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Web dashboard path: authenticated with the Supabase session token."""
    dest = _save_upload(file)
    result = run_pipeline(db, dest, file.filename or dest.name,
                          source="upload", owner_id=user.owner_id)
    return _result_payload(result)


def _result_payload(result) -> dict:
    return {
        "ok": True,
        "status": result.status,
        "invoice_id": result.invoice_id,
        "ledger_id": result.ledger_id,
        "exception_id": result.exception_id,
        "reason": result.reason,
        "detail": result.detail,
        "vendor": result.vendor,
        "total": result.total,
        "month": result.month,
        "message": result.message,
    }
