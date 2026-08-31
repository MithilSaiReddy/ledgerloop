import json
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ExceptionRow, Invoice, LedgerEntry, UserSettings
from app.routes.ledger import telegram_get_ledger, _latest_month_with_data

OWNER = "owner-tg-123"
TG_USER = "999000111"


def _make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False)
    db = S()
    db.add(UserSettings(
        owner_id=OWNER, shop_name="Testki Store", state_code="29",
        telegram_chat_id=TG_USER,
    ))
    inv = Invoice(owner_id=OWNER, filename="a.pdf", source="telegram")
    db.add(inv)
    db.flush()

    def add_entry(date, type_, total, invoice_no):
        db.add(LedgerEntry(
            owner_id=OWNER, invoice_id=inv.id, vendor="Vendor",
            invoice_no=invoice_no, date=date, type=type_,
            taxable_value=total, cgst=0.0, sgst=0.0, igst=0.0, total=total,
            category="general",
        ))

    add_entry("2025-06-02", "purchase", 2000.0, "1")
    add_entry("2025-06-03", "purchase", 3000.0, "2")
    add_entry("2025-06-05", "sale", 1500.0, "3")
    add_entry("2025-07-01", "purchase", 500.0, "4")

    db.add(ExceptionRow(
        owner_id=OWNER, invoice_id=inv.id, reason="TAX_MISMATCH",
        status="open", month="2025-06", detail="check",
    ))
    db.commit()
    return db


def _call(db, month=None):
    return telegram_get_ledger(month=month, telegram_user_id=TG_USER, db=db)


class TestLatestMonth:
    def test_picks_latest_month_when_none(self):
        db = _make_db()
        assert _latest_month_with_data(db, OWNER) == "2025-07"

    def test_returns_none_when_no_data(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        assert _latest_month_with_data(db, OWNER) is None


class TestTelegramLedger:
    def test_totals_for_june(self):
        db = _make_db()
        d = _call(db, "2025-06")
        assert d["month"] == "2025-06"
        assert d["count"] == 3
        assert d["purchases"] == 2
        assert d["sales"] == 1
        assert d["money_in"] == 1500.0
        assert d["money_out"] == 5000.0
        assert d["net"] == -3500.0
        assert d["open_exceptions"] == 1

    def test_defaults_to_latest_month(self):
        db = _make_db()
        d = _call(db)
        assert d["month"] == "2025-07"
        assert d["count"] == 1

    def test_unknown_user_raises_401(self):
        db = _make_db()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            telegram_get_ledger(month="2025-06", telegram_user_id="nobody", db=db)
        assert exc.value.status_code == 401
