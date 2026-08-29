"""LedgerLoop MCP server — exposes the FastAPI pipeline as Hermes Agent tools.

Zero third-party dependencies: speaks Model Context Protocol (JSON-RPC 2.0
over stdio) with the Python stdlib only, so it can run inside Hermes' own
venv without touching its environment.

Register with a self-hosted Hermes instance:

    hermes mcp add ledgerloop -- python /path/to/ledgerloop/hermes/mcp_server.py

Then the agent gets two tools:
    ingest_invoice(file_path, user_id)
    trigger_month_end(user_id, month?)
"""

import json
import os
import sys
import urllib.request
import urllib.error

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

TOOLS = [
    {
        "name": "ingest_invoice",
        "description": (
            "Ingest an invoice photo/PDF into the LedgerLoop ledger. Returns a "
            "one-line status like 'Parsed: Vendor X, Rs 4200' or 'Flagged: reason'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Local path to the invoice file"},
                "user_id": {"type": "string", "description": "Telegram user id of the sender"},
            },
            "required": ["file_path", "user_id"],
        },
    },
    {
        "name": "trigger_month_end",
        "description": (
            "Bundle the month's reconciled ledger + open exceptions and email the "
            "summary to the CA. Ask the user to confirm before calling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "month": {"type": "string", "description": "YYYY-MM, defaults to current month"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "notify_exception",
        "description": (
            "Send a Telegram notification to the shop owner about an invoice "
            "that was flagged for manual review. Call this whenever ingest "
            "returns a flagged or failed status. Successes stay silent."
        ),
        "inputSchema": {
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
]


def _http_post(url: str, *, files: dict | None = None, data: dict | None = None,
               params: dict | None = None) -> dict:
    if params:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(params)}"
    boundary = "----LedgerLoopFormBoundary7d1a"
    body = b""
    for k, v in (data or {}).items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        ).encode()
    for k, (fname, content) in (files or {}).items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
            f"filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "message": f"backend error {e.code}: {e.read().decode()[:200]}"}


def _telegram_send(chat_id: str, text: str) -> None:
    import json as _json
    import urllib.request as _ur

    req = _ur.Request(
        f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_BOT_TOKEN', '')}/sendMessage",
        data=_json.dumps({"chat_id": chat_id, "text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with _ur.urlopen(req, timeout=30):
        pass


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


def tool_call(name: str, args: dict) -> str:
    if name == "ingest_invoice":
        import datetime as dt
        import mimetypes
        import pathlib

        p = pathlib.Path(args["file_path"])
        if not p.exists():
            return f"File not found: {p}"
        result = _http_post(
            f"{BACKEND_URL}/invoices/ingest",
            files={"file": (p.name, p.read_bytes())},
            data={"user_id": args["user_id"], "_ts": dt.datetime.now().isoformat()},
        )
        status = result.get("status", "")
        # Give the agent enough structure to decide whether notify_exception
        # is warranted (successes stay silent).
        extra = ""
        if status == "exception":
            extra = (
                f"\nSTATUS: exception\nREASON_CODE: {result.get('reason', '')}"
                f"\nMONTH: {result.get('month', '')}\n"
                "Call notify_exception to alert the owner."
            )
        elif status == "failed":
            extra = (
                f"\nSTATUS: failed\nREASON_CODE: {result.get('reason', '')}\n"
                "Call notify_exception to alert the owner."
            )
        return result.get("message", json.dumps(result)) + extra

    if name == "trigger_month_end":
        import datetime as dt

        month = args.get("month") or dt.date.today().strftime("%Y-%m")
        # POST with no body but query param -> use urllib with empty data
        req = urllib.request.Request(
            f"{BACKEND_URL}/month-end/send?month={month}", data=b"", method="POST"
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
        s = result["bundle"]["summary"]
        mode = "sent" if not result.get("dry_run") else "prepared (dry-run, not emailed)"
        return (
            f"Month-end {month} {mode}: {s['count']} invoices, "
            f"Rs {s['grand_total']:,.0f}, {s['open_exceptions']} open exceptions."
        )

    if name == "notify_exception":
        chat_id = args["chat_id"]
        filename = args["filename"]
        reason = args.get("reason", "")
        month = args.get("month", "")
        friendly = FRIENDLY_REASONS.get(
            reason, (reason or "it needs review").lower().replace("_", " ")
        )
        origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
        link = f"{origin}/exceptions" + (f"?month={month}" if month else "")
        _telegram_send(chat_id, (
            "⚠️ Invoice needs attention\n\n"
            f"{friendly}.\n"
            f"File: {filename}\n\n"
            f"👉 Review it: {link}"
        ))
        return f"Notified owner about {filename} ({reason})."

    return f"Unknown tool: {name}"


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ledgerloop", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        try:
            text = tool_call(params["name"], params.get("arguments") or {})
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": text}]},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": f"error: {exc}"}],
                           "isError": True},
            }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if msg_id is not None:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
