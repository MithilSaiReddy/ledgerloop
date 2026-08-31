import json

from email.mime.multipart import MIMEMultipart

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.emailer import build_ca_message, build_month_bundle, render_html
from app.models import Invoice, LedgerEntry
from app.routes.export import purchase_register_csv, sales_register_csv

OWNER = "owner-email-test"


def _make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False)
    db = S()
    inv = Invoice(owner_id=OWNER, filename="a.pdf", source="telegram")
    db.add(inv)
    db.flush()
    db.add(LedgerEntry(
        owner_id=OWNER, invoice_id=inv.id, vendor="Sultatha Textiles",
        gstin="29ABCDE1234F1Z5", invoice_no="710", date="2025-09-03", type="sale",
        taxable_value=15714.29, cgst=392.86, sgst=392.86, igst=0.0, total=16500.0,
        category="apparel", place_of_supply="29-Karnataka", is_interstate=False,
        items=json.dumps([{"description": "Kurti", "hsn_code": "6204",
                           "quantity": 2, "rate": 8250.0, "amount": 16500.0}]),
    ))
    db.add(LedgerEntry(
        owner_id=OWNER, invoice_id=inv.id, vendor="Bombay Hardware Co.",
        gstin="27BBBBB1234F1Z7", invoice_no="99", date="2025-09-07", type="purchase",
        taxable_value=10000.0, cgst=900.0, sgst=900.0, igst=0.0, total=11800.0,
        category="hardware", is_interstate=False,
    ))
    db.commit()
    return db


def _attachments(msg) -> list[str]:
    out = []
    for part in msg.walk():
        fn = part.get_filename()
        if fn:
            out.append(fn)
    return out


class TestRegisterBuilders:
    def test_purchase_csv_text(self):
        db = _make_db()
        text = purchase_register_csv(db, "2025-09", OWNER)
        lines = text.strip().splitlines()
        assert lines[0] == (
            "GSTIN of Supplier,Supplier Name,Invoice Number,Invoice Date,"
            "Invoice Value,Taxable Value,CGST,SGST,IGST"
        )
        assert len(lines) == 2
        assert "Bombay Hardware Co." in lines[1] and "07-09-2025" in lines[1]

    def test_sales_csv_text(self):
        db = _make_db()
        text = sales_register_csv(db, "2025-09", OWNER)
        lines = text.strip().splitlines()
        assert lines[0].startswith("GSTIN of Recipient,")
        assert len(lines) == 2
        assert "Sultatha Textiles" in lines[1] and "03-09-2025" in lines[1]


class TestPreviewIsSimple:
    def test_no_overview_sections(self):
        db = _make_db()
        bundle = build_month_bundle(db, "2025-09", OWNER)
        html = render_html(bundle, db, OWNER).lower()
        assert "registers for ca review" in html
        assert "purchase register (attached)" in html
        assert "sales register (attached)" in html
        # The old full overview is gone.
        for banned in ("by category", "line items", "exceptions", "open exceptions",
                       "grand total"):
            assert banned not in html


class TestCaMessage:
    def test_subject_and_body(self):
        db = _make_db()
        subject, msg, bundle = build_ca_message(db, "2025-09", OWNER, "ca@example.com")
        assert subject == "[LedgerLoop] 2025-09 registers for CA review"
        assert isinstance(msg, MIMEMultipart)
        assert bundle["summary"]["count"] == 2

    def test_exactly_two_csv_attachments(self):
        db = _make_db()
        _, msg, _ = build_ca_message(db, "2025-09", OWNER, "ca@example.com")
        files = _attachments(msg)
        assert files == ["purchases-2025-09.csv", "sales-2025-09.csv"]

    def test_attachments_are_csv_subtype(self):
        db = _make_db()
        _, msg, _ = build_ca_message(db, "2025-09", OWNER, "ca@example.com")
        csv_parts = [p for p in msg.walk() if p.get_content_type() == "application/csv"]
        assert len(csv_parts) == 2
        bodies = {p.get_filename(): p.get_payload(decode=True).decode() for p in csv_parts}
        assert "Invoice Value" in bodies["purchases-2025-09.csv"]
        assert "Customer Name" in bodies["sales-2025-09.csv"]

    def test_content_hash_set(self):
        db = _make_db()
        _, msg, _ = build_ca_message(db, "2025-09", OWNER, "ca@example.com")
        assert len(msg.content_hash) == 16

    def test_empty_month_still_attaches_both(self):
        db = _make_db()
        _, msg, bundle = build_ca_message(db, "2025-10", OWNER, "ca@example.com")
        assert bundle["summary"]["count"] == 0
        assert _attachments(msg) == ["purchases-2025-10.csv", "sales-2025-10.csv"]