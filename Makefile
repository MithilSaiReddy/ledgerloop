.PHONY: demo full dev seed test clean

## 🟢 Offline demo — no accounts needed. One command.
demo:
	cp -n .env.example .env || true
	docker compose up --build

## 🔷 Full stack — real Supabase + Google + LLM (fill .env first).
full:
	docker compose up --build

## 💻 Local dev without Docker.
dev:
	uv venv --python 3.12 .venv >/dev/null 2>&1 || true
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

## Seed the demo DB with the 60 sample invoices (local SQLite).
seed:
	.venv/bin/python data/generator.py
	PYTHONPATH=backend .venv/bin/python backend/scripts/ingest_all.py --fresh

## Run backend tests.
test:
	PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q

## Stop and remove containers + demo volumes/data.
clean:
	docker compose down -v
	rm -rf data/demo-samples data/*.db
