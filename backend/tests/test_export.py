import csv
import io
import json
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Invoice, LedgerEntry
from app.routes.export import export_ledger, _fmt_date

OWNER = "owner-test-123"


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
        party_name=None, gstin="29ABCDE1234F1Z5", invoice_no="710",
        date="2025-09-03", type="sale", taxable_value=15714.29,
        cgst=392.86, sgst=392.86, igst=0.0, total=16500.0,
        category="apparel", place_of_supply="29-Karnataka", is_interstate=False,
        items=json.dumps([
            {"description": "Kurti", "hsn_code": "6204", "quantity": 2,
             "rate": 8250.0, "amount": 16500.0},
        ]),
    ))
    db.add(LedgerEntry(
        owner_id=OWNER, invoice_id=inv.id, vendor="Bombay Hardware Co.",
        party_name="Bombay Hardware Co.", gstin="27BBBBB1234F1Z7", invoice_no="99",
        date="2025-09-07", type="purchase", taxable_value=10000.0,
        cgst=900.0, sgst=900.0, igst=0.0, total=11800.0,
        category="hardware", is_interstate=False,
        items=json.dumps([{"description": "Wrench", "hsn_code": "8204", "quantity": 1,
                           "rate": 10000.0, "amount": 10000.0}]),
    ))
    db.commit()
    return db


def _call(db, format="csv", type="all"):
    return export_ledger(
        month="2025-09",
        format=format,
        type=type,
        db=db,
        user=types.SimpleNamespace(owner_id=OWNER),
    )


class TestRegisterColumns:
    def test_purchase_register_headers(self):
        db = _make_db()
        body = _call(db, type="purchase").body.decode()
        assert body.splitlines()[0] == (
            "GSTIN of Supplier,Supplier Name,Invoice Number,Invoice Date,"
            "Invoice Value,Taxable Value,CGST,SGST,IGST"
        )

    def test_sales_register_headers(self):
        db = _make_db()
        body = _call(db, type="sales").body.decode()
        assert body.splitlines()[0] == (
            "GSTIN of Recipient,Customer Name,Invoice Number,Invoice Date,"
            "Place of Supply,Invoice Value,Taxable Value,CGST,SGST,IGST"
        )

    def test_purchase_register_excludes_sales_and_vice_versa(self):
        db = _make_db()
        purchases = list(csv.DictReader(io.StringIO(_call(db, type="purchase").body.decode())))
        sales = list(csv.DictReader(io.StringIO(_call(db, type="sales").body.decode())))
        assert [r["Invoice Number"] for r in purchases] == ["99"]
        assert [r["Invoice Number"] for r in sales] == ["710"]

    def test_one_row_per_bill_not_per_item(self):
        db = _make_db()
        sales = list(csv.DictReader(io.StringIO(_call(db, type="sales").body.decode())))
        assert len(sales) == 1
        assert set(sales[0].keys()).isdisjoint({"description", "hsn_code", "quantity", "rate", "amount"})

    def test_dates_are_dd_mm_yyyy(self):
        db = _make_db()
        sales = list(csv.DictReader(io.StringIO(_call(db, type="sales").body.decode())))
        assert sales[0]["Invoice Date"] == "03-09-2025"
        purchases = list(csv.DictReader(io.StringIO(_call(db, type="purchase").body.decode())))
        assert purchases[0]["Invoice Date"] == "07-09-2025"

    def test_party_name_falls_back_to_vendor(self):
        db = _make_db()
        sales = list(csv.DictReader(io.StringIO(_call(db, type="sales").body.decode())))
        assert sales[0]["Customer Name"] == "Sultatha Textiles"

    def test_values_and_filenames(self):
        db = _make_db()
        res = _call(db, type="purchase")
        assert 'filename="purchases-2025-09.csv"' in res.headers["content-disposition"]
        purchases = list(csv.DictReader(io.StringIO(res.body.decode())))
        assert purchases[0]["Invoice Value"] == "11800.0"
        assert purchases[0]["CGST"] == "900.0"
        assert purchases[0]["IGST"] == "0.0"
        res = _call(db, type="sales")
        assert 'filename="sales-2025-09.csv"' in res.headers["content-disposition"]
        assert '"29-Karnataka"' in res.body.decode() or "29-Karnataka" in res.body.decode()


class TestJsonExport:
    def test_keeps_full_detail_including_items(self):
        db = _make_db()
        res = _call(db, format="json")
        rows = json.loads(res.body)
        assert len(rows) == 2
        sale = next(r for r in rows if r["type"] == "sale")
        assert sale["items"] == [{"description": "Kurti", "hsn_code": "6204", "quantity": 2,
                                  "rate": 8250.0, "amount": 16500.0}]
        assert 'filename="ledgerloop-2025-09.json"' in res.headers["content-disposition"]


class TestFmtDate:
    def test_iso_to_dd_mm_yyyy(self):
        assert _fmt_date("2025-09-03") == "03-09-2025"

    def test_garbage_passthrough(self):
        assert _fmt_date("") == ""
        assert _fmt_date("03-09-2025") == "03-09-2025"