"""Month-end summary builder + Gmail API sender.

Bounded by design: sends only what's passed in, logs an audit record with a
content hash, and honours EMAIL_DRY_RUN so nothing leaves the machine unless
explicitly configured. Sends via the Gmail API using the owner's own Google
OAuth tokens (stored in user_settings), never a shared SMTP account.
"""

import base64
import hashlib
import json
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, ExceptionRow, Invoice, LedgerEntry

logger = logging.getLogger(__name__)

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def serialize_ledger(e: LedgerEntry) -> dict:
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


def render_html(bundle: dict) -> str:
    s = bundle["summary"]
    cat_rows = "".join(
        f"<tr><td>{cat}</td><td style='text-align:right'>₹{amt:,.2f}</td></tr>"
        for cat, amt in s["by_category"].items()
    )
    entry_rows = "".join(
        f"<tr><td>{e['date']}</td><td>{e['vendor']}</td><td>{e['invoice_no']}</td>"
        f"<td>{e['gstin'] or '—'}</td><td style='text-align:right'>₹{e['taxable_value']:,.2f}</td>"
        f"<td style='text-align:right'>₹{e['cgst']:,.2f}</td>"
        f"<td style='text-align:right'>₹{e['sgst']:,.2f}</td>"
        f"<td style='text-align:right'>₹{e['igst']:,.2f}</td>"
        f"<td style='text-align:right'><b>₹{e['total']:,.2f}</b></td></tr>"
        for e in bundle["entries"]
    )
    exc_rows = "".join(
        f"<li><b>{x['reason']}</b> — {x['detail']} <i>({x['filename']}, {x['status']})</i></li>"
        for x in bundle["exceptions"]
    ) or "<li>None 🎉</li>"

    return f"""<html><body style="font-family:sans-serif">
<h2>LedgerLoop month-end summary — {bundle['month']}</h2>
<p><b>{s['count']}</b> reconciled invoices · <b>{s['open_exceptions']}</b> open exceptions</p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>Taxable</th><th>CGST</th><th>SGST</th><th>IGST</th><th>Grand total</th></tr>
<tr><td style="text-align:right">₹{s['taxable_value']:,.2f}</td>
<td style="text-align:right">₹{s['cgst']:,.2f}</td>
<td style="text-align:right">₹{s['sgst']:,.2f}</td>
<td style="text-align:right">₹{s['igst']:,.2f}</td>
<td style="text-align:right"><b>₹{s['grand_total']:,.2f}</b></td></tr>
</table>
<h3>By category</h3>
<table border="1" cellpadding="4" cellspacing="0">{cat_rows}</table>
<h3>Invoice detail</h3>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Date</th><th>Vendor</th><th>Invoice #</th><th>GSTIN</th><th>Taxable</th><th>CGST</th><th>SGST</th><th>IGST</th><th>Total</th></tr>
{entry_rows}
</table>
<h3>Exceptions ({len(bundle['exceptions'])})</h3>
<ul>{exc_rows}</ul>
<p style="color:#888;font-size:12px">Generated by LedgerLoop. Figures are auto-extracted and pending CA review — no filing has been done.</p>
</body></html>"""


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


def send_via_gmail_api(user_settings, to_email: str, subject: str, html: str) -> None:
    from googleapiclient.discovery import build

    creds = _gmail_creds(user_settings)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = build("gmail", "v1", credentials=creds)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_month_end(db: Session, month: str, user) -> dict:
    from app.models import UserSettings

    settings = get_settings()
    bundle = build_month_bundle(db, month, user.owner_id)
    html = render_html(bundle)
    content_hash = hashlib.sha256(html.encode()).hexdigest()[:16]

    user_settings = db.get(UserSettings, user.owner_id)
    ca_email = (user_settings.ca_email if user_settings else "") or user.email
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
        send_via_gmail_api(
            user_settings, ca_email,
            f"[LedgerLoop] Month-end ledger + exceptions — {month}", html,
        )
        note = f"sent to {ca_email} via Gmail API; content_hash={content_hash}"

    db.add(AuditLog(
        actor="system", action="month_end_send", entity_type="send",
        owner_id=user.owner_id,
        before_json=None,
        after_json=json.dumps({
            "month": month, "invoice_count": len(bundle["entries"]),
            "exception_count": len(bundle["exceptions"]), "hash": content_hash,
            "to": ca_email,
        }),
        note=note,
    ))
    db.commit()

    return {"month": month, "dry_run": not can_send, "note": note, "bundle": bundle}
