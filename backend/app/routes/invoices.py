import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.db import get_db
from app.models import Invoice, UserSettings
from app.pipeline.runner import run_pipeline

router = APIRouter(prefix="/invoices", tags=["invoices"])

ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff",
                ".tif", ".txt", ".docx", ".xlsx", ".html", ".eml", ".csv"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _safe_filename(filename: str | None) -> str:
    """Return a bare filename with no path components.

    Strips both Unix ('/') and Windows ('\\') separators so a hostile upload
    name can't escape the upload directory. Falls back to a safe default.
    """
    name = Path((filename or "").replace("\\", "/")).name.strip()
    if name in ("", ".", ".."):
        return "upload.bin"
    return name


def _save_upload(file: UploadFile) -> Path:
    raw = file.filename or ""
    ext = Path(raw).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file type: {ext or 'unknown'}")
    contents = file.file.read(MAX_BYTES + 1)
    if len(contents) > MAX_BYTES:
        raise HTTPException(400, "File is larger than 10 MB")

    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / _safe_filename(raw)

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
def ingest_invoice(
    file: UploadFile = File(...),
    user_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Telegram path: authenticated via the Telegram -> owner mapping."""
    dest = _save_upload(file)
    owner_id = _owner_for_telegram(db, user_id)

    result = run_pipeline(db, dest, dest.name,
                          source="api", telegram_user_id=user_id, owner_id=owner_id)
    return _result_payload(result)


@router.post("/upload")
def upload_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Web dashboard path: authenticated with the Supabase session token."""
    dest = _save_upload(file)
    result = run_pipeline(db, dest, dest.name,
                          source="upload", owner_id=user.owner_id)
    return _result_payload(result)


@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Original bill: return the stored Markdown text of an uploaded invoice."""
    inv = _get_owned_invoice(db, invoice_id, user.owner_id)
    return {
        "id": inv.id,
        "filename": inv.filename,
        "source": inv.source,
        "converter_used": inv.converter_used,
        "raw_text": inv.raw_text or "",
    }


@router.get("/{invoice_id}/file")
def get_invoice_file(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Original digital bill: stream the stored upload itself (photo/PDF), so
    the shopkeeper can inspect the actual document, not just the OCR text."""
    from fastapi.responses import FileResponse

    inv = _get_owned_invoice(db, invoice_id, user.owner_id)
    path = Path(get_settings().upload_dir) / inv.filename
    if not path.exists():
        raise HTTPException(404, "original file is not available on this server")
    return FileResponse(
        path,
        media_type=_guess_media_type(path),
        filename=inv.filename,
        content_disposition_type="inline",
    )


def _get_owned_invoice(db: Session, invoice_id: int, owner_id: str) -> Invoice:
    inv = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.owner_id == owner_id)
        .first()
    )
    if inv is None:
        raise HTTPException(404, "invoice not found")
    return inv


def _guess_media_type(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _result_payload(result) -> dict:
    payload = {
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
        "extracted": result.extracted,
    }
    if result.status == "ledger" and result.ledger_id is not None:
        row = result.ledger_row()
        if row:
            payload["entry"] = row
    return payload
