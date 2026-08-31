# LedgerLoop 🧾

**AI finance-controller agent for Indian shopkeepers** — Razorpay AI Buildathon,
Track 4 (AI Finance Controller).

Shopkeepers forward invoice photos/PDFs on Telegram or upload them on the web →
the backend runs them through a parse → structure → reconcile pipeline →
clean invoices land in a single ledger; anything ambiguous gets flagged with a
plain-language reason and an instant Telegram notification → at month-end, one
confirmed command emails the summary + exception list to the CA. A dashboard
lets the shopkeeper/CA fix misread fields first, and every edit is audited.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | Next.js 16 (App Router, RSC) + shadcn/ui + Tailwind, Google login via Supabase Auth |
| API | FastAPI + SQLAlchemy + Supabase Postgres (row-level security per owner) |
| Parsing | MarkItDown (PDFs/docs) + OCR for images: Mistral OCR (via `LLM_API_KEY` + `OCR_MODEL`) first on camera photos, pytesseract fallback |
| Structuring | Mistral API (OpenAI-compatible; Llama 3.3 on Groq works too — `LLM_*` env vars) |
| Telegram | Standalone `python-telegram-bot` worker: forward invoices to a bot → POSTed to the backend API |
| Email | Gmail API with the owner's own OAuth token (no shared SMTP account), `EMAIL_DRY_RUN` guard |

## Reconciliation rules

1. **DUPLICATE** — same normalized `(vendor, invoice_no)` already in ledger
2. **INVALID_GSTIN** — regex + official mod-36 checksum validation
3. **GSTIN_MISSING** / **EXTRACTION_INCOMPLETE** — required fields unreadable
4. **TAX_MISMATCH** — `taxable_value + cgst + sgst + igst ≠ total` beyond ₹1 tolerance
5. **HSN_MISSING** — HSN/SAC code missing or invalid, needed for GST filing
6. **TAX_TREATMENT_MISMATCH** — intra/inter-state tax treatment doesn't match the place of supply
7. **BAD_DATE** — unparseable date

Hard failures (unreadable file, LLM unavailable) also land in `exceptions`
(`CONVERSION_FAILED`, `LLM_UNAVAILABLE`, `EXTRACTION_FAILED`) so nothing ever
silently vanishes. No auto-filing, no auto-approval — resolving an exception or
sending to the CA always requires a human action, and every such action is
appended to `audit_log`.

## Run it

Pick a tier — **Demo** needs zero external accounts, **Full** uses real
Supabase + Google + an LLM.

### 🟢 Demo (recommended for a first look — no accounts)

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:3000**. The backend auto-detects the empty Supabase
vars, runs on a local SQLite DB, and seeds 60 sample invoices (48 clean +
12 exceptions). You're dropped straight into the dashboard (a green **Demo**
badge shows you're offline) — browse the ledger, review exceptions, run a
month-end send (dry-run), and upload a sample file to watch it flow through
the pipeline. No Google login, no API keys.

> Demo mode is active whenever no real Supabase backend is configured
> (`SUPABASE_DB_URL`/`SUPABASE_URL` empty). Set `DEMO_MODE=0` in `.env` to force
> real auth even in that case. The local SQLite DB lives at `data/ledgerloop.db`.

### 🔷 Full (real Supabase + Google + LLM)

```bash
cp .env.example .env   # fill it in once:
# 1. Create a Supabase project -> paste SUPABASE_* keys + JWT secret
# 2. Google OAuth client -> enable the Google provider in Supabase Auth,
#    add scopes: openid,email,profile,https://www.googleapis.com/auth/gmail.send
# 3. Paste SUPABASE_URL/ANON_KEY into NEXT_PUBLIC_SUPABASE_*
# 4. Add LLM_API_KEY (Mistral), optionally TELEGRAM_BOT_TOKEN
# 5. In the Supabase SQL editor, run the migrations in filename order —
#    001, 002, 003_* and 004 (all additive, safe on a fresh or existing DB)
# 6. Clear DEMO_MODE (or leave it — the backend demo self-disables once a real
#    Supabase backend is configured). ALSO clear NEXT_PUBLIC_DEMO_MODE: the
#    frontend stays in demo mode while that is set to `1`

docker compose up --build
```

### 💻 Local dev (no Docker)

```bash
uv venv --python 3.12 .venv && .venv/bin/pip install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --port 8000 --app-dir backend   # API
cd frontend && npm install && npm run dev                               # UI
```

Services: Dashboard :3000 · API :8000. Open :3000 → sign in with Google →
upload invoices or forward them to your Telegram bot.


### Telegram

Send invoices straight to a Telegram bot — no agent needed. A standalone worker
(`telegram/bot.py`) polls Telegram and POSTs each photo/PDF to the backend's
`/invoices/ingest`, then replies with the status. All parsing, structuring and
reconciliation happens in the backend.

```bash
# docker `telegram` service runs automatically when TELEGRAM_BOT_TOKEN is set
TELEGRAM_BOT_TOKEN=<your-bot-token> docker compose up --build
```

Commands the bot understands: `/start`, `/chatid`, `/audit`, `/monthend YYYY-MM`.
Exceptions can be reviewed right in chat with **Approve / Dismiss / View** inline
buttons. `/monthend` sends on behalf of the owner linked to your chat — grab the
mapping from `/chatid`.

## Dataset & evaluation

Sample invoices are generated on the fly (not stored in git). Demo mode
regenerates them into `data/demo-samples/` and auto-ingests into SQLite on first
startup. For manual/eval runs:

```bash
.venv/bin/python data/generator.py          # 60 synthetic GST invoices (48 clean + 12 messy)
PYTHONPATH=backend .venv/bin/python backend/scripts/ingest_all.py            # local SQLite
# or inside Docker (Postgres):
docker compose exec -e SAMPLES_DIR=/app/data/samples -e DEMO_OWNER_ID=<uuid> backend \
    python scripts/ingest_all.py
PYTHONPATH=backend .venv/bin/python eval/evaluate.py   # honest metrics vs hand labels
```

Eval reports total processed, auto-match rate, false-positive rate (flagged but
fine), exception recall, per-field extraction accuracy — plus a verbatim list of
every mismatch. Nothing is cherry-picked.


## Layout

```
backend/    FastAPI app, pipeline (convert→structure→reconcile), models, tests
            supabase/migrations/ — incremental schema + RLS (001, 002, 003_*, 004)
frontend/   Next.js 16 dashboard: Google login (or demo mode), /upload /ledger /exceptions /audit /send
telegram/   standalone Telegram ingestion worker (bot.py + Dockerfile)
data/       invoice generator, synthetic samples (generated on the fly), ground truth labels
eval/       evaluation harness CLI
```

### Demo mode details

- **Backend** (`app/config.py`): `demo_mode_on` is `True` when `DEMO_MODE=1`
  (default) and no real `SUPABASE_DB_URL`/`SUPABASE_URL` is set. It auto-falls
  back to local SQLite and, on first startup, seeds the 48+12 sample invoices
  for `DEMO_OWNER_ID` using an offline deterministic extractor (no LLM/network).
- **Auth** (`app/auth.py`): demo mode scopes every request to the demo owner,
  so the dashboard works with no token. Real Supabase JWT verification is
  untouched when a backend is configured.
- **Frontend**: `NEXT_PUBLIC_DEMO_MODE=1` (or empty Supabase keys) synthesizes a
  demo session — you land straight on the dashboard with a **Demo** badge.
