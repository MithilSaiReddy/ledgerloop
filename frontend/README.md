# LedgerLoop frontend

Next.js 16 (App Router, React Server Components) dashboard for LedgerLoop — the
AI finance-controller for Indian shopkeepers: Google login (or demo mode), the
ledger, exception review, audit log, settings and month-end send.

Full project docs are in the [root README](../README.md).

## Development

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # production build
npm run start      # serve the production build
npm run lint       # eslint
```

## Environment

All `NEXT_PUBLIC_*` values are baked into the browser bundle at build time;
`process.env.BACKEND_URL` is read at request time on the server (required for
the server-side data fetches in `/ledger`, `/exceptions`, `/audit`, `/send`).

| Variable | Used by | Purpose |
| --- | --- | --- |
| `BACKEND_URL` | server | API base URL for server-side fetches (e.g. `http://localhost:8000`, or `http://backend:8000` inside Docker) |
| `NEXT_PUBLIC_BACKEND_URL` | browser | API base URL for client calls — must be reachable from the browser (e.g. `http://localhost:8000`) |
| `NEXT_PUBLIC_SUPABASE_URL` | browser | Supabase project URL for Google auth |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | browser | Supabase anon key |
| `NEXT_PUBLIC_DEMO_MODE` | browser | `1` forces offline demo (no login); empty auto-detects: demo runs whenever the Supabase browser keys are empty |

Copy the template: `cp ../.env.example .env` (see the root README for the
demo vs. full tiers).