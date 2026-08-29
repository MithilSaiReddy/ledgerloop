import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(32), default="telegram")
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    converter_used: Mapped[str] = mapped_column(String(32), default="markitdown")
    extracted_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # raw LLM output
    status: Mapped[str] = mapped_column(String(32), default="processing")  # ledger | exception | processing | failed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class LedgerEntry(Base):
    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    vendor: Mapped[str]
    party_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    invoice_no: Mapped[str]
    date: Mapped[str]  # YYYY-MM-DD; month key is date[:7]
    month: Mapped[str] = mapped_column(String(7), default="", index=True)
    type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # purchase | sale | null (legacy rows)
    taxable_value: Mapped[float] = mapped_column(Float)
    cgst: Mapped[float] = mapped_column(Float, default=0.0)
    sgst: Mapped[float] = mapped_column(Float, default=0.0)
    igst: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(64), default="uncategorized")
    hsn_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    place_of_supply: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_interstate: Mapped[Optional[bool]] = mapped_column(nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_file_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    edited_fields: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of field names touched by human
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class ExceptionRow(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    reason: Mapped[str]  # DUPLICATE | INVALID_GSTIN | GSTIN_MISSING | TAX_MISMATCH | EXTRACTION_INCOMPLETE | ...
    detail: Mapped[str] = mapped_column(Text, default="")
    extracted_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved | dismissed
    resolved_ledger_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ledger.id"), nullable=True)
    # billing month of the invoice (from parsed date; falls back to ingestion month)
    month: Mapped[str] = mapped_column(String(7), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64))  # agent | dashboard | system
    action: Mapped[str]  # edit_ledger | resolve_exception | month_end_send | ingest
    entity_type: Mapped[str]  # ledger | exception | send
    entity_id: Mapped[Optional[int]]
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ca_email: Mapped[str] = mapped_column(String(256), default="")
    shop_name: Mapped[str] = mapped_column(String(256), default="")
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    state_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    gst_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_token_expiry: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
