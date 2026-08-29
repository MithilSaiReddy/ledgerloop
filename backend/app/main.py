import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routes import exceptions, export, invoices, ledger, month_end, user_settings

logging.basicConfig(level=logging.INFO)

settings = get_settings()


def _seed_demo_if_needed() -> None:
    """In demo mode, generate + ingest the sample dataset on first startup so
    the dashboard is pre-populated with no external accounts."""
    if not settings.demo_mode_on or not settings.seed_demo:
        return
    try:
        import sys as _sys
        from pathlib import Path as _P

        root = _P(__file__).resolve().parent.parent.parent
        if str(root) not in _sys.path:
            _sys.path.insert(0, str(root))

        from app.models import LedgerEntry

        db = SessionLocal()
        try:
            has_rows = db.query(LedgerEntry.id).first() is not None
        finally:
            db.close()
        if has_rows:
            logging.getLogger(__name__).info("demo ledger already populated — skipping seed")
            return

        from data.generator import generate
        from scripts.ingest_all import ingest_samples

        samples_dir = generate(Path(settings.demo_samples_dir))
        counts = ingest_samples(settings.demo_owner_id, samples_dir,
                                source="demo", verbose=True)
        logging.getLogger(__name__).info(
            "Demo seed complete: %s", counts)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception("Demo seed failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_demo_if_needed()
    yield


app = FastAPI(title="LedgerLoop API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again in a moment."},
    )


app.include_router(invoices.router)
app.include_router(ledger.router)
app.include_router(exceptions.router)
app.include_router(month_end.router)
app.include_router(export.router)
app.include_router(user_settings.router)


@app.get("/health")
def health():
    return {"ok": True, "service": "ledgerloop-api"}
