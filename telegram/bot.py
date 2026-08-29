"""Telegram ingestion worker.

Any photo/document sent to the bot is POSTed to /invoices/ingest and the bot
echoes the backend's one-line status. Runs standalone — no agent required;
all invoice parsing/structuring/reconciliation happens in the FastAPI backend.

Docker:  TELEGRAM_BOT_TOKEN=... docker compose up telegram
Local:   TELEGRAM_BOT_TOKEN=... BACKEND_URL=http://localhost:8000 python bot.py
"""

import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
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
    "EXTRACTION_INCOMPLETE": "we couldn't read all the key fields",
    "BAD_DATE": "the invoice date is unreadable",
    "CONVERSION_FAILED": "we couldn't read this file",
    "LLM_UNAVAILABLE": "invoice processing is temporarily unavailable",
    "EXTRACTION_FAILED": "we couldn't extract the key details",
}


def friendly_reason(reason: str) -> str:
    return FRIENDLY_REASONS.get(reason, (reason or "it needs review").lower().replace("_", " "))


def reply_for(result: dict) -> str:
    """Status-based reply: silent-success style confirm for ledger entries,
    a notification with deep link for exceptions, an error for failures."""
    status = result.get("status")
    if status == "ledger":
        vendor = result.get("vendor") or "vendor"
        total = result.get("total")
        amount = f"₹{total:,.0f} " if total is not None else ""
        return f"✅ Got it — {amount}from {vendor}"
    if status == "exception":
        reason = result.get("reason", "")
        month = result.get("month", "")
        link = f"{FRONTEND_ORIGIN}/exceptions" + (f"?month={month}" if month else "")
        return (
            f"⚠️ Invoice needs attention\n\n"
            f"{friendly_reason(reason)}.\n"
            f"File: {result.get('filename', 'invoice')}\n\n"
            f"👉 Review it: {link}"
        )
    detail = result.get("detail") or result.get("message") or "Please try again."
    return f"❌ Sorry, that didn't work.\n{detail}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "Namaste! Send me an invoice photo or PDF and I'll file it in your ledger.\n\n"
        f"Your chat ID is: {chat_id}\n"
        "Paste it into Settings on the dashboard so I know which ledger is yours.\n\n"
        "Commands:\n"
        "/chatid — show this chat ID again\n"
        "/monthend YYYY-MM — email summary + exceptions to your CA"
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
    filename = getattr(msg.document, "file_name", None) or f"{tg_file.file_unique_id}.jpg"

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
        else:
            reply = reply_for(result)
    except Exception:
        reply = f"❌ Backend error ({resp.status_code})"
    await msg.reply_text(reply)


async def month_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month = context.args[0] if context.args else None
    if not month:
        await update.message.reply_text("Usage: /monthend 2025-06")
        return
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{BACKEND_URL}/month-end/send", params={"month": month})
    try:
        data = resp.json()
        s = data["bundle"]["summary"]
        mode = "sent ✉️" if not data.get("dry_run") else "prepared (dry-run, not emailed)"
        await update.message.reply_text(
            f"📧 Month-end {month} {mode}: {s['count']} invoices, "
            f"₹{s['grand_total']:,.0f}, {s['open_exceptions']} open exceptions."
        )
    except Exception:
        await update.message.reply_text(f"❌ Month-end failed ({resp.status_code})")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chat_id))
    app.add_handler(CommandHandler("monthend", month_end))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    log.info("LedgerLoop bot polling…")
    app.run_polling()


if __name__ == "__main__":
    main()
