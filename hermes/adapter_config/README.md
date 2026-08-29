# Hermes Agent integration (INSTALLED)

The Nous Research Hermes Agent (v0.20.5) is installed at `~/.hermes/hermes-agent`.

## What's wired

- `hermes/mcp_server.py` — zero-dependency MCP stdio server exposing two tools:
  - `ingest_invoice(file_path, user_id)` → POSTs to `/invoices/ingest`, returns
    the one-line status ("✅ Parsed: Vendor X, ₹4,200" / "⚠️ Flagged: GSTIN missing")
  - `trigger_month_end(user_id, month?)` → POSTs to `/month-end/send`
- Registered with Hermes as an MCP server named `ledgerloop`:

```bash
hermes mcp add ledgerloop --command python3 \
  --args /home/mithil/Documents/ailedger/hermes/mcp_server.py \
  --env "BACKEND_URL=http://localhost:8000"
```

Verify with `hermes mcp list`. Start a new `hermes chat` session and the agent
has both tools available.

## Telegram

Two options:

1. **Hermes gateway (agent-driven):** `hermes gateway install` then configure a
   Telegram channel — the agent handles messages and calls the MCP tools.
   Recommended system prompt addition:

```
You are LedgerLoop, a finance-controller assistant for an Indian shopkeeper.
When the user sends a document/photo path or file, call ingest_invoice(file_path,
user_id) and reply ONLY with the one-line status it returns — do not editorialize.
For month-end requests, summarize what will be sent and require an explicit
"confirm" reply before calling trigger_month_end. Never invent ledger numbers;
always fetch them via the tools.
```

2. **Fallback worker (no Hermes needed):** `hermes/telegram_bot.py`
   (`python hermes/telegram_bot.py`) — plain python-telegram-bot that POSTs any
   photo/document straight to `/invoices/ingest`. Use this if Hermes is down.

## Safety rails

- The agent can only *ingest* and *trigger month-end*; it cannot edit ledger rows
  or resolve exceptions (dashboard-only, human-only).
- Month-end send requires explicit user confirmation AND writes an audit_log row
  with a content hash; EMAIL_DRY_RUN=true blocks real emails by default.
