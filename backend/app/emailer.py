"""Month-end summary builder + Gmail API sender.

Bounded by design: sends only what's passed in, logs an audit record with a
content hash, and honours EMAIL_DRY_RUN so nothing leaves the machine unless
explicitly configured. Sends via the Gmail API using the owner's own Google
OAuth tokens (stored in user_settings), never a shared SMTP account.
"""

import base64
import csv
import hashlib
import json
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, ExceptionRow, Invoice, LedgerEntry

logger = logging.getLogger(__name__)

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def serialize_ledger(e: LedgerEntry) -> dict:
    items = []
    raw_items = getattr(e, "items", None)
    if raw_items:
        try:
            parsed = json.loads(raw_items)
            if isinstance(parsed, list):
                items = parsed
        except (TypeError, ValueError):
            items = []
    return {
        "id": e.id,
        "invoice_id": e.invoice_id,
        "owner_id": e.owner_id,
        "type": getattr(e, "type", None),
        "vendor": e.vendor,
        "party_name": getattr(e, "party_name", None),
        "gstin": e.gstin,
        "invoice_no": e.invoice_no,
        "date": e.date,
        "month": getattr(e, "month", None) or (e.date[:7] if e.date else None),
        "taxable_value": e.taxable_value,
        "cgst": e.cgst,
        "sgst": e.sgst,
        "igst": e.igst,
        "total": e.total,
        "category": e.category,
        "hsn_code": getattr(e, "hsn_code", None),
        "place_of_supply": getattr(e, "place_of_supply", None),
        "is_interstate": getattr(e, "is_interstate", None),
        "tax_note": getattr(e, "tax_note", None),
        "items": items,
    }


def build_month_bundle(db: Session, month: str, owner_id: str) -> dict:
    """Bundle everything for one month. `month` is YYYY-MM."""
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.owner_id == owner_id)
        .filter(LedgerEntry.date.like(f"{month}%"))
        .order_by(LedgerEntry.date)
        .all()
    )
    exceptions = (
        db.query(ExceptionRow, Invoice.filename)
        .join(Invoice, ExceptionRow.invoice_id == Invoice.id)
        .filter(ExceptionRow.owner_id == owner_id)
        .filter(or_(ExceptionRow.month == month, ExceptionRow.month == ""))
        .all()
    )

    by_category: dict[str, float] = {}
    total_taxable = total_cgst = total_sgst = total_igst = grand_total = 0.0
    for e in entries:
        by_category[e.category] = round(by_category.get(e.category, 0.0) + e.total, 2)
        total_taxable += e.taxable_value
        total_cgst += e.cgst
        total_sgst += e.sgst
        total_igst += e.igst
        grand_total += e.total

    return {
        "month": month,
        "entries": [serialize_ledger(e) for e in entries],
        "exceptions": [
            {
                "id": x.id,
                "filename": fname,
                "reason": x.reason,
                "detail": x.detail,
                "status": x.status,
            }
            for x, fname in exceptions
        ],
        "summary": {
            "count": len(entries),
            "taxable_value": round(total_taxable, 2),
            "cgst": round(total_cgst, 2),
            "sgst": round(total_sgst, 2),
            "igst": round(total_igst, 2),
            "grand_total": round(grand_total, 2),
            "by_category": dict(sorted(by_category.items())),
            "open_exceptions": sum(1 for x, _ in exceptions if x.status == "open"),
        },
    }


def render_html(bundle: dict, db: Session, owner_id: str) -> str:
    """Simple email body: short note + the exact register CSVs inline.

    No overview summary, no by-category table, no line items, no exception
    list — the CA gets the same two registers that the download buttons give
    (attached as CSVs), preceded by a short covering note.
    """
    from app.routes.export import purchase_register_csv, sales_register_csv

    month = bundle["month"]
    entries = bundle["entries"]

    n_sales = sum(1 for e in entries if e.get("type") == "sale")
    n_purchases = sum(1 for e in entries if e.get("type") == "purchase")

    def _table(side: str, heading: str, csv_text: str) -> str:
        lines = [ln for ln in csv_text.strip().splitlines() if ln]
        if not lines:
            return ""
        thead = "".join(f"<th>{h}</th>" for h in lines[0].split(","))
        body = ""
        for ln in lines[1:]:
            cells = next(csv.reader([ln]))
            body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        return (
            f"<h3>{heading} ({side})</h3>"
            f"<table border='1' cellpadding='4' cellspacing='0'>"
            f"<tr>{thead}</tr>{body}</table>"
        )

    return f"""<html><body style="font-family:sans-serif">
<h2>LedgerLoop — {month} registers for CA review</h2>
<p>Hi, please find attached the purchase and sales registers for <b>{month}</b>
({n_sales} sales bills, {n_purchases} purchase bills). They're the same files you
can download from your dashboard — one row per bill, GST-register format.</p>
<p>Figures are auto-extracted from your bills and <b>pending your review</b> — no
returns have been filed.</p>
{_table('attached', 'Purchase register', purchase_register_csv(db, month, owner_id))}
{_table('attached', 'Sales register', sales_register_csv(db, month, owner_id))}
<p style="color:#888;font-size:12px">Generated by LedgerLoop.</p>
</body></html>"""


def _plain_text(bundle: dict) -> str:
    entries = bundle["entries"]
    n_sales = sum(1 for e in entries if e.get("type") == "sale")
    n_purchases = sum(1 for e in entries if e.get("type") == "purchase")
    return (
        f"LedgerLoop — {bundle['month']} registers for CA review\n\n"
        f"Hi, please find attached the purchase and sales registers for "
        f"{bundle['month']} ({n_sales} sales bills, {n_purchases} purchase bills). "
        "They're the same files you can download from the dashboard — one row "
        "per bill, GST-register format.\n\n"
        "Figures are auto-extracted from your bills and pending your review — "
        "no returns have been filed.\n\n— LedgerLoop"
    )


def build_ca_message(db: Session, month: str, owner_id: str, to_email: str):
    """Build the CA email: short note + both register CSVs as attachments.

    Returns (subject, msg, bundle) where `msg` is a ready-to-send MIMEMultipart
    with the CSVs attached and its `content_hash` set over body + CSV bytes.
    """
    from app.routes.export import purchase_register_csv, sales_register_csv

    bundle = build_month_bundle(db, month, owner_id)
    html = render_html(bundle, db, owner_id)
    purchases = purchase_register_csv(db, month, owner_id)
    sales = sales_register_csv(db, month, owner_id)

    subject = f"[LedgerLoop] {month} registers for CA review"
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["To"] = to_email
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(_plain_text(bundle), "plain"))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)
    for name, text in (("purchases", purchases), ("sales", sales)):
        part = MIMEApplication(text.encode("utf-8"), _subtype="csv")
        part.add_header("Content-Disposition", "attachment",
                        filename=f"{name}-{month}.csv")
        msg.attach(part)
    msg.content_hash = hashlib.sha256(
        (purchases + sales + html).encode("utf-8")
    ).hexdigest()[:16]
    return subject, msg, bundle


def _gmail_creds(user_settings):
    """Build Google OAuth credentials from the owner's stored tokens,
    refreshing (and persisting the new access token) when expired."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest

    settings = get_settings()
    creds = Credentials(
        token=user_settings.google_access_token,
        refresh_token=user_settings.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=[GMAIL_SCOPE],
    )
    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
        user_settings.google_access_token = creds.token
    return creds


def send_via_gmail_api(user_settings, to_email: str, msg) -> None:
    from googleapiclient.discovery import build

    creds = _gmail_creds(user_settings)
    msg["To"] = to_email
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = build("gmail", "v1", credentials=creds)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_month_end(db: Session, month: str, user) -> dict:
    from app.models import UserSettings

    settings = get_settings()
    user_settings = db.get(UserSettings, user.owner_id)
    ca_email = (user_settings.ca_email if user_settings else "") or user.email
    subject, msg, bundle = build_ca_message(db, month, user.owner_id, ca_email)
    content_hash = msg.content_hash

    can_send = (
        not settings.email_dry_run
        and user_settings is not None
        and bool(user_settings.google_refresh_token)
        and bool(ca_email)
        and settings.google_client_id
        and settings.google_client_secret
    )

    if not can_send:
        note = f"dry-run (EMAIL_DRY_RUN={settings.email_dry_run}); content_hash={content_hash}"
        logger.info("month-end %s NOT sent: %s", month, note)
    else:
        send_via_gmail_api(user_settings, ca_email, msg)
        note = f"sent to {ca_email} via Gmail API ({len(bundle['entries'])} bills); content_hash={content_hash}"

    db.add(AuditLog(
        actor="system", action="month_end_send", entity_type="send",
        owner_id=user.owner_id,
        before_json=None,
        after_json=json.dumps({
            "month": month, "invoice_count": len(bundle["entries"]),
            "exception_count": len(bundle["exceptions"]), "hash": content_hash,
            "to": ca_email, "attachments": [f"purchases-{month}.csv", f"sales-{month}.csv"],
        }),
        note=note,
    ))
    db.commit()

    return {"month": month, "dry_run": not can_send, "note": note, "bundle": bundle}
