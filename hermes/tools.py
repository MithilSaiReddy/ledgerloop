"""Hermes Agent custom tools for LedgerLoop.

These are plain functions with JSON-schema descriptions so they can be
registered as Hermes tool calls (OpenAI-compatible function-calling format).
Each tool is a thin, safe wrapper over the FastAPI backend — the agent never
touches the DB or pipeline directly.
"""

import json
import os
from pathlib import Path

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

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


def format_exception_msg(filename: str, reason: str, month: str) -> str:
    link = f"{FRONTEND_ORIGIN}/exceptions" + (f"?month={month}" if month else "")
    return (
        f"⚠️ Invoice needs attention\n\n"
        f"{friendly_reason(reason)}.\n"
        f"File: {filename}\n\n"
        f"👉 Review it: {link}"
    )


def send_telegram_message(chat_id: str, text: str) -> None:
    httpx.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30.0,
    ).raise_for_status()


def _post(path: str, **kwargs) -> dict:
    resp = httpx.post(f"{BACKEND_URL}{path}", timeout=120.0, **kwargs)
    return resp.json()


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "ingest_invoice",
            "description": (
                "Ingest an invoice photo or PDF into the LedgerLoop ledger. "
                "Returns a one-line status: parsed OK or flagged with reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Local path to the downloaded invoice file",
                    },
                    "user_id": {"type": "string", "description": "Telegram user id"},
                },
                "required": ["file_path", "user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_month_end",
            "description": (
                "Bundle the month's reconciled ledger + open exceptions and email "
                "the summary to the shopkeeper's CA. Requires explicit user "
                "confirmation before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "month": {
                        "type": "string",
                        "description": "Month as YYYY-MM; defaults to current month if omitted",
                    },
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_exception",
            "description": (
                "Send a Telegram notification to the shop owner about an invoice "
                "that was flagged for manual review. Call this whenever ingest "
                "returns a flagged or failed status. Successes stay silent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat id of the owner"},
                    "filename": {"type": "string"},
                    "reason": {"type": "string", "description": "Machine reason code, e.g. INVALID_GSTIN"},
                    "month": {"type": "string", "description": "Billing month YYYY-MM if known"},
                },
                "required": ["chat_id", "filename", "reason"],
            },
        },
    },
]


def ingest_invoice(file_path: str, user_id: str) -> str:
    p = Path(file_path)
    if not p.exists():
        return f"❌ File not found: {file_path}"
    with open(p, "rb") as fh:
        result = _post(
            "/invoices/ingest",
            files={"file": (p.name, fh)},
            data={"user_id": user_id},
        )
    return result.get("message", "❌ Ingest failed")


def trigger_month_end(user_id: str, month: str | None = None) -> str:
    import datetime as dt

    month = month or dt.date.today().strftime("%Y-%m")
    result = _post("/month-end/send", params={"month": month}, data={"confirmed_by": user_id})
    if not result.get("dry_run"):
        return f"📧 Month-end summary for {month} sent to your CA ({result['bundle']['summary']['count']} invoices)."
    s = result["bundle"]["summary"]
    return (
        f"📧 Month-end summary for {month} prepared in dry-run mode "
        f"({s['count']} invoices, ₹{s['grand_total']:,.0f}, {s['open_exceptions']} open exceptions) — "
        "not emailed because EMAIL_DRY_RUN is on."
    )


def notify_exception(chat_id: str, filename: str, reason: str, month: str | None = None) -> str:
    send_telegram_message(chat_id, format_exception_msg(filename, reason, month or ""))
    return f"Notified owner about {filename} ({reason})."


AVAILABLE_TOOLS = {
    "ingest_invoice": ingest_invoice,
    "trigger_month_end": trigger_month_end,
    "notify_exception": notify_exception,
}


def execute_tool(name: str, arguments: str | dict) -> str:
    args = json.loads(arguments) if isinstance(arguments, str) else arguments
    fn = AVAILABLE_TOOLS.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    return fn(**args)


if __name__ == "__main__":
    print(json.dumps(TOOL_SCHEMAS, indent=2))
