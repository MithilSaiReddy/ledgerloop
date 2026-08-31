"""Pipeline orchestrator: convert -> structure -> reconcile -> DB write.

Every ingest lands in exactly one of three states:
- invoices.status='ledger'     + row in ledger
- invoices.status='exception'  + row in exceptions with a reason
- invoices.status='failed'     + nothing usable was extracted at all
                                  (+ an exceptions row so it never vanishes)
"""

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import AuditLog, ExceptionRow, Invoice, LedgerEntry, UserSettings
from app.pipeline.convert import IMAGE_EXTS, markitdown_convert, ocr_image_convert
from app.pipeline.reconcile import parse_date, reconcile
from app.pipeline.structure import StructureError, demo_structure, llm_structure

logger = logging.getLogger(__name__)


class PipelineResult:
    def __init__(
        self,
        invoice_id: int,
        status: str,
        message: str,
        reason: str | None = None,
        detail: str = "",
        exception_id: int | None = None,
        ledger_id: int | None = None,
        vendor: str = "",
        total: float | None = None,
        month: str = "",
        extracted: dict | None = None,
    ):
        self.invoice_id = invoice_id
        self.status = status  # 'ledger' | 'exception' | 'failed'
        self.message = message  # one-liner for the Telegram reply
        self.reason = reason
        self.detail = detail
        self.exception_id = exception_id
        self.ledger_id = ledger_id
        self.vendor = vendor
        self.total = total
        self.month = month
        self.extracted = extracted

    def ledger_row(self) -> dict | None:
        """Serialized ledger entry if this invoice was auto-matched."""
        if self.status != "ledger" or self.ledger_id is None:
            return None
        from app.emailer import serialize_ledger

        entry = db_session_get(self)
        return serialize_ledger(entry) if entry else None


def db_session_get(result: "PipelineResult"):
    db = SessionLocal()
    try:
        return db.get(LedgerEntry, result.ledger_id)
    finally:
        db.close()


def _existing_pairs(db: Session, owner_id: str) -> set[tuple[str, str]]:
    from app.pipeline.reconcile import normalize_vendor

    return {
        (normalize_vendor(v), str(n))
        for v, n in db.query(LedgerEntry.vendor, LedgerEntry.invoice_no)
        .filter(LedgerEntry.owner_id == owner_id)
        .all()
    }


def _owner_gst_context(db: Session, owner_id: str) -> dict:
    """The shop's GST profile so reconcile can decide intra- vs inter-state
    tax treatment and apply owner-specific auto-derive GST rates."""
    row = db.get(UserSettings, owner_id)
    if row is None:
        return {}
    tax_rates: dict | None = None
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


def run_pipeline(
    db: Session,
    file_path: Path,
    filename: str,
    source: str = "telegram",
    telegram_user_id: str | None = None,
    owner_id: str = "",
) -> PipelineResult:
    settings = get_settings()
    invoice = Invoice(
        filename=filename, source=source, telegram_user_id=telegram_user_id,
        owner_id=owner_id,
    )
    db.add(invoice)
    db.commit()

    # 1. Convert to Markdown text. Photos prefer the vision-backed Mistral OCR
    #    (much more accurate on real phone shots than tesseract); fall back to
    #    the offline path when the API is unavailable or no key is set.
    try:
        if file_path.suffix.lower() in IMAGE_EXTS and settings.llm_api_key:
            try:
                text = ocr_image_convert(
                    file_path, settings.llm_api_key,
                    base_url=settings.llm_base_url, model=settings.ocr_model,
                )
                converter = "mistral-ocr"
            except Exception as exc:  # noqa: BLE001
                logger.warning("mistral OCR failed on %s: %s; falling back", filename, exc)
                text, converter = markitdown_convert(file_path)
        else:
            text, converter = markitdown_convert(file_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("convert failed for %s: %s", filename, exc)
        return _failure(db, invoice, "CONVERSION_FAILED",
                        f"We couldn't read {filename}. It may be corrupted or in an unsupported format.",
                        raw_text=f"[conversion error: {exc}]")

    invoice.raw_text = text
    invoice.converter_used = converter

    # 2. Structure the invoice. In demo mode (no real Supabase backend) the
    #    deterministic offline extractor is used instead of the paid LLM so the
    #    sample dataset ingests with zero keys/network.
    if settings.demo_mode_on and not settings.llm_api_key:
        try:
            extracted = demo_structure(text)
        except Exception as exc:  # noqa: BLE001
            logger.error("demo structure failed for %s: %s", filename, exc)
            return _failure(db, invoice, "EXTRACTION_FAILED",
                            f"We couldn't extract the key details from {filename}.",
                            raw_text=text)
    else:
        if not settings.llm_api_key:
            return _failure(db, invoice, "LLM_UNAVAILABLE",
                            "Invoice processing is temporarily unavailable. Please try again in a few minutes.",
                            raw_text=text)

        try:
            extracted = llm_structure(
                text, settings.llm_api_key,
                model=settings.llm_model, base_url=settings.llm_base_url,
            )
        except StructureError as exc:
            logger.error("structure failed for %s: %s", filename, exc)
            return _failure(db, invoice, "EXTRACTION_FAILED",
                            f"We couldn't extract the key details from {filename}. Please check the file and try again.",
                            raw_text=text)

    invoice.extracted_json = json.dumps(extracted, ensure_ascii=False)

    # 3. Reconcile: ledger or exception.
    owner = _owner_gst_context(db, owner_id)
    row, reason, detail = reconcile(extracted, _existing_pairs(db, owner_id), owner=owner)

    if row is not None:
        row = {**row, "items": json.dumps(row.get("items") or [], ensure_ascii=False)}
        entry = LedgerEntry(invoice_id=invoice.id, owner_id=owner_id, **row)
        db.add(entry)
        invoice.status = "ledger"
        db.add(AuditLog(actor="agent", action="ingest", entity_type="ledger",
                        owner_id=owner_id,
                        before_json=None, after_json=json.dumps(row),
                        note=f"auto-ingested from {filename}"))
        db.commit()
        amount = f"₹{row['total']:,.0f}"
        return PipelineResult(
            invoice.id, "ledger",
            f"✅ Parsed: {row['vendor']}, {amount}",
            ledger_id=entry.id,
            vendor=row["vendor"], total=row["total"],
            month=(parse_date(row["date"]) or "")[:7],
            extracted=extracted,
        )

    parsed_date = parse_date(extracted.get("date"))
    exc_row = ExceptionRow(
        invoice_id=invoice.id,
        owner_id=owner_id,
        reason=reason,
        detail=detail,
        extracted_json=json.dumps(extracted, ensure_ascii=False),
        month=parsed_date[:7] if parsed_date else "",
    )
    db.add(exc_row)
    invoice.status = "exception"
    db.add(AuditLog(actor="agent", action="ingest", entity_type="exception",
                    owner_id=owner_id,
                    after_json=json.dumps({"reason": reason, "detail": detail}),
                    note=f"flagged from {filename}"))
    db.commit()
    return PipelineResult(
        invoice.id, "exception",
        f"⚠️ Flagged: {_short_reason(reason)}",
        reason=reason, detail=detail, exception_id=exc_row.id,
        vendor=str(extracted.get("vendor") or ""),
        month=parsed_date[:7] if parsed_date else "",
        extracted=extracted,
    )


def _failure(db: Session, invoice: Invoice, reason: str, friendly: str,
             raw_text: str = "") -> PipelineResult:
    """Record a hard failure as both invoice.status='failed' AND an exceptions
    row, so the shopkeeper always sees it on their review queue."""
    invoice.status = "failed"
    invoice.raw_text = raw_text or invoice.raw_text
    exc_row = ExceptionRow(
        invoice_id=invoice.id,
        owner_id=invoice.owner_id,
        reason=reason,
        detail=friendly,
        extracted_json=None,
        month="",  # undated: show on every month's queue
    )
    db.add(exc_row)
    db.add(AuditLog(actor="system", action="ingest", entity_type="exception",
                    owner_id=invoice.owner_id,
                    after_json=json.dumps({"reason": reason}),
                    note=f"failed to process {invoice.filename}"))
    db.commit()
    return PipelineResult(
        invoice.id, "failed",
        f"❌ {friendly}",
        reason=reason, detail=friendly, exception_id=exc_row.id,
    )


def _short_reason(reason: str) -> str:
    mapping = {
        "DUPLICATE": "duplicate invoice",
        "INVALID_GSTIN": "invalid GSTIN",
        "GSTIN_MISSING": "GSTIN missing",
        "TAX_MISMATCH": "tax amounts don't add up",
        "EXTRACTION_INCOMPLETE": "could not read all fields",
        "BAD_DATE": "invoice date unreadable",
        "CONVERSION_FAILED": "file could not be read",
        "LLM_UNAVAILABLE": "processing temporarily unavailable",
        "EXTRACTION_FAILED": "could not extract fields",
    }
    return mapping.get(reason, reason.lower())
