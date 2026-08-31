"""Telegram ingestion worker.

Any photo/document sent to the bot is POSTed to /invoices/ingest and the bot
echoes the backend's one-line status. Runs standalone — no agent required;
all invoice parsing/structuring/reconciliation happens in the FastAPI backend.

Docker:  TELEGRAM_BOT_TOKEN=... docker compose up telegram
Local:   TELEGRAM_BOT_TOKEN=... BACKEND_URL=http://localhost:8000 python bot.py
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import httpx

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ledgerloop-bot")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

FRIENDLY_REASONS = {
    "DUPLICATE": "this invoice looks like a duplicate",
    "INVALID_GSTIN": "the GSTIN on this invoice doesn't appear to be valid",
    "GSTIN_MISSING": "the GSTIN is missing from this invoice",
    "TAX_MISMATCH": "the tax amounts don't add up",
    "TAX_TREATMENT_MISMATCH": "the tax split doesn't match whether it's intra- or inter-state",
    "HSN_MISSING": "the HSN/SAC code is missing and is needed for GST filing",
    "EXTRACTION_INCOMPLETE": "we couldn't read all the key fields",
    "BAD_DATE": "the invoice date is unreadable",
    "CONVERSION_FAILED": "we couldn't read this file",
    "LLM_UNAVAILABLE": "invoice processing is temporarily unavailable",
    "EXTRACTION_FAILED": "we couldn't extract the key details",
}


def friendly_reason(reason: str) -> str:
    return FRIENDLY_REASONS.get(reason, (reason or "it needs review").lower().replace("_", " "))


def _fmt_money(v) -> str:
    if v is None:
        return "—"
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _detail_lines(result: dict) -> str:
    """Human-readable summary of what the extractor read, so the shopkeeper
    can see at a glance whether the details came out right."""
    ex = result.get("extracted") or {}
    entry = result.get("entry") or ex

    vendor = entry.get("vendor") or result.get("vendor") or ex.get("vendor")
    lines = []
    if vendor:
        lines.append(f"Vendor: {vendor}")
    inv = entry.get("invoice_no") or ex.get("invoice_no")
    if inv:
        lines.append(f"Invoice #: {inv}")
    date = entry.get("date") or ex.get("date")
    if date:
        lines.append(f"Date: {date}")
    total = _fmt_money(entry.get("total") if entry.get("total") is not None else ex.get("total"))
    lines.append(f"Amount: {total}")
    gstin = entry.get("gstin") or ex.get("gstin")
    if gstin:
        lines.append(f"GSTIN: {gstin}")
    typ = entry.get("type") or ex.get("type")
    if typ in ("purchase", "sale"):
        lines.append(f"Type: {'sale (money in)' if typ == 'sale' else 'purchase (money out)'}")
    cgst = entry.get("cgst") if entry.get("cgst") is not None else ex.get("cgst")
    sgst = entry.get("sgst") if entry.get("sgst") is not None else ex.get("sgst")
    igst = entry.get("igst") if entry.get("igst") is not None else ex.get("igst")
    if any(v not in (None, 0, 0.0) for v in (cgst, sgst, igst)):
        lines.append(f"CGST {_fmt_money(cgst)} · SGST {_fmt_money(sgst)} · IGST {_fmt_money(igst)}")
    tax_note = entry.get("tax_note") or ex.get("tax_note")
    if tax_note:
        lines.append(f"Tax: {tax_note}")
    items = entry.get("items") or ex.get("items") or []
    if isinstance(items, list) and items:
        lines.append(f"Line items: {len(items)}")
    return "\n".join(lines) if lines else ""


def reply_for(result: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    """Status-based reply: silent-success style confirm for ledger entries,
    a notification with inline review buttons for exceptions, an error for
    failures. Returns (text, optional inline keyboard)."""
    status = result.get("status")
    details = _detail_lines(result)
    if status == "ledger":
        vendor = result.get("vendor") or "vendor"
        total = result.get("total")
        amount = f"₹{total:,.0f} " if total is not None else ""
        head = f"✅ Got it — {amount}from {vendor}"
        text = f"{head}\n\n{details}" if details else head
        return text, None
    if status == "exception":
        reason = result.get("reason", "")
        month = result.get("month", "")
        link = f"{FRONTEND_ORIGIN}/exceptions" + (f"?month={month}" if month else "")
        text = (
            f"⚠️ Invoice needs attention\n\n"
            f"{friendly_reason(reason)}.\n"
            f"File: {result.get('filename', 'invoice')}\n"
            f"{details}\n\n"
            f"👉 Review on web: {link}"
        )
        exc_id = result.get("exception_id")
        if exc_id:
            row = [
                InlineKeyboardButton("👁 View", callback_data=f"exc:{exc_id}:view"),
            ]
            row2 = [
                InlineKeyboardButton("✅ Approve", callback_data=f"exc:{exc_id}:approve"),
                InlineKeyboardButton("❌ Dismiss", callback_data=f"exc:{exc_id}:dismiss"),
            ]
            markup = InlineKeyboardMarkup([row, row2])
            return text, markup
        return text, None
    detail = result.get("detail") or result.get("message") or "Please try again."
    return f"❌ Sorry, that didn't work.\n{detail}", None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "Namaste! Send me an invoice photo or PDF and I'll file it in your ledger.\n\n"
        f"Your chat ID is: {chat_id}\n"
        "Paste it into Settings on the dashboard so I know which ledger is yours.\n\n"
        "Tip: send the bill as a File 📎 (not a compressed photo) — it reads more accurately.\n\n"
        "Commands:\n"
        "/send — email this month's registers to your CA\n"
        "/send 2025-06 — email a specific month to your CA\n"
        "/ledger — see this month's totals\n"
        "/ledger 2025-06 — see a specific month's totals\n"
        "/audit — see recent activity in your ledger\n"
        "/chatid — show this chat ID again"
    )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Your chat ID is: {update.effective_chat.id}\n"
        "Paste it into Settings → Telegram chat ID on the dashboard."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    tg_file = msg.document or msg.photo[-1]
    file = await context.bot.get_file(tg_file.file_id)
    raw_name = getattr(msg.document, "file_name", None) or f"{tg_file.file_unique_id}.jpg"
    filename = Path(raw_name).name or "invoice.jpg"

    tmp_path = f"/tmp/opencode/{filename}"
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    await file.download_to_drive(tmp_path)

    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(tmp_path, "rb") as fh:
            resp = await client.post(
                f"{BACKEND_URL}/invoices/ingest",
                files={"file": (filename, fh)},
                data={"user_id": str(msg.from_user.id)},
            )
    try:
        result = resp.json()
        result.setdefault("filename", filename)
        if resp.status_code == 401 or (isinstance(result.get("detail"), str) and "Telegram" in result["detail"]):
            reply = (
                "⚠️ Your Telegram isn't linked to a ledger yet.\n\n"
                f"Your chat ID is: {msg.from_user.id}\n"
                "Open the LedgerLoop dashboard → Settings → paste it under "
                "'Telegram chat ID', then send me the invoice again."
            )
            markup = None
        else:
            reply, markup = reply_for(result)
    except Exception:
        reply = f"❌ Backend error ({resp.status_code})"
        markup = None
    await msg.reply_text(reply, reply_markup=markup)


def _exception_view_text(exc: dict) -> str:
    """Human-readable render of a full exception record (for the View button)."""
    seen = exc.get("extracted") or {}
    lines = [f"📄 Exception #{exc.get('id')}"]
    lines.append(f"Reason: {friendly_reason(exc.get('reason', ''))}")
    if exc.get("detail"):
        lines.append(f"Detail: {exc['detail']}")
    entry = seen
    vendor = entry.get("vendor")
    if vendor:
        lines.append(f"\nVendor: {vendor}")
    inv = entry.get("invoice_no")
    if inv:
        lines.append(f"Invoice #: {inv}")
    date = entry.get("date")
    if date:
        lines.append(f"Date: {date}")
    total = _fmt_money(entry.get("total"))
    lines.append(f"Amount: {total}")
    typ = entry.get("type")
    if typ in ("purchase", "sale"):
        lines.append(f"Type: {'sale (money in)' if typ == 'sale' else 'purchase (money out)'}")
    items = entry.get("items") or []
    if isinstance(items, list) and items:
        lines.append(f"Line items: {len(items)}")
        for it in items[:10]:
            desc = str(it.get("description") or "—")
            amount = _fmt_money(it.get("amount"))
            lines.append(f"  • {desc} — {amount}")
        if len(items) > 10:
            lines.append(f"  … and {len(items) - 10} more")
    return "\n".join(lines)


async def exception_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the inline View/Approve/Dismiss buttons on exception replies."""
    query = update.callback_query
    await query.answer()
    _, exc_id_str, action = (query.data or "").split(":")
    exc_id = int(exc_id_str)
    chat_id = str(update.effective_user.id)

    async with httpx.AsyncClient(timeout=60.0) as client:
        if action == "view":
            resp = await client.get(
                f"{BACKEND_URL}/telegram/exceptions/{exc_id}",
                params={"telegram_user_id": chat_id},
            )
            if resp.status_code == 200:
                await query.message.reply_text(_exception_view_text(resp.json()))
            else:
                await query.message.reply_text(f"⚠️ Couldn't load that exception ({resp.status_code}).")
            return

        resolved = "resolved" if action == "approve" else "dismissed"
        resp = await client.post(
            f"{BACKEND_URL}/telegram/exceptions/{exc_id}/resolve",
            data={"telegram_user_id": chat_id, "action": resolved},
        )
        if resp.status_code == 200:
            stamp = "✅ Approved — added to ledger." if resolved == "resolved" else "❌ Dismissed — not added."
        elif resp.status_code == 400:
            stamp = f"⏭️ {resp.json().get('detail', 'already handled')}."
        else:
            stamp = f"⚠️ Couldn't update ({resp.status_code})."
        await query.edit_message_text(
            f"{stamp}\n\n{query.message.text}",
            reply_markup=None,
        )


async def audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_user.id)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{BACKEND_URL}/telegram/audit",
            params={"telegram_user_id": chat_id, "limit": 20},
        )
    if resp.status_code != 200:
        await update.message.reply_text(f"❌ Audit failed ({resp.status_code}).")
        return
    rows = resp.json()
    if not rows:
        await update.message.reply_text("No activity recorded yet.")
        return
    lines = ["🕘 Recent activity:"]
    for r in rows:
        action = r.get("action", "")
        note = r.get("note") or ""
        when = (r.get("created_at") or "")[:10]
        lines.append(f"• {when} {action} — {note}")
    await update.message.reply_text("\n".join(lines[:22]))


async def ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_user.id)
    month = context.args[0] if context.args else None
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{BACKEND_URL}/telegram/ledger",
            params={"telegram_user_id": chat_id, "month": month} if month
            else {"telegram_user_id": chat_id},
        )
    if resp.status_code == 401:
        await update.message.reply_text(
            "⚠️ Your Telegram isn't linked to a ledger yet.\n"
            f"Your chat ID is: {chat_id}\n"
            "Open the LedgerLoop dashboard → Settings → paste it under "
            "'Telegram chat ID'."
        )
        return
    if resp.status_code != 200:
        await update.message.reply_text(f"❌ Couldn't load the ledger ({resp.status_code}).")
        return
    d = resp.json()
    month = d["month"]
    if d["count"] == 0:
        await update.message.reply_text(f"📒 {month}: no bills recorded.")
        return
    s = d
    lines = [
        f"📒 {month}",
        f"Bills: {s['count']}  ({s['purchases']} purchases · {s['sales']} sales)",
        f"Money in  {_fmt_money(s['money_in'])}",
        f"Money out {_fmt_money(s['money_out'])}",
        f"Net       {_fmt_money(s['net'])}",
        f"GST       {_fmt_money(s['gst'])}",
    ]
    if s["open_exceptions"]:
        lines.append(f"⚠️ {s['open_exceptions']} open exception(s)")
    await update.message.reply_text("\n".join(lines))


async def _perform_month_end_send(chat_id: str, month: str, message) -> None:
    """Shared POST to run the CA month-end send and reply with the summary."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BACKEND_URL}/telegram/month-end/send",
            data={"month": month, "telegram_user_id": chat_id},
        )
    try:
        if resp.status_code == 401:
            await message.reply_text(
                "⚠️ Your Telegram isn't linked to a ledger yet.\n"
                f"Your chat ID is: {chat_id}\n"
                "Open the LedgerLoop dashboard → Settings → paste it under "
                "'Telegram chat ID'."
            )
            return
        if resp.status_code != 200:
            raise ValueError(resp.text)
        data = resp.json()
        s = data["bundle"]["summary"]
        mode = "sent ✉️" if not data.get("dry_run") else "prepared (dry-run, not emailed)"
        await message.reply_text(
            f"📧 Month-end {month} {mode}: {s['count']} invoices, "
            f"₹{s['grand_total']:,.0f}, {s['open_exceptions']} open exceptions."
        )
    except Exception:
        await message.reply_text(f"❌ Month-end failed ({resp.status_code})")


async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month = context.args[0] if context.args else None
    if month and len(month) != 7:
        await update.message.reply_text("Usage: /send 2025-06 (or /send for this month)")
        return
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    chat_id = str(update.effective_user.id)
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, email my CA", callback_data=f"sendc:{month}:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"sendc:{month}:cancel"),
        ]
    ])
    await update.message.reply_text(
        f"Send the {month} purchase & sales registers + a note to your CA?\n"
        "No filing happens automatically — just the monthly email.",
        reply_markup=markup,
    )


async def send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /send confirmation buttons (Yes / Cancel)."""
    query = update.callback_query
    await query.answer()
    _, month, action = (query.data or "").split(":")
    chat_id = str(update.effective_user.id)
    if action == "cancel":
        await query.edit_message_text("❌ Send cancelled. Nothing was emailed.")
        return
    await query.edit_message_text(f"⏳ Sending {month} to your CA…")
    await _perform_month_end_send(chat_id, month, query.message)


async def month_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month = context.args[0] if context.args else None
    if not month:
        await update.message.reply_text("Usage: /monthend 2025-06")
        return
    chat_id = str(update.effective_user.id)
    await _perform_month_end_send(chat_id, month, update.message)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chat_id))
    app.add_handler(CommandHandler("audit", audit))
    app.add_handler(CommandHandler("monthend", month_end))
    app.add_handler(CommandHandler("send", send))
    app.add_handler(CommandHandler("ledger", ledger))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(CallbackQueryHandler(exception_callback, pattern=r"^exc:"))
    app.add_handler(CallbackQueryHandler(send_callback, pattern=r"^sendc:"))
    log.info("LedgerLoop bot polling…")
    app.run_polling()


if __name__ == "__main__":
    main()
