"""LedgerLoop evaluation harness.

Runs every sample in data/samples/ through the REAL pipeline (markitdown ->
(Mistral) -> reconcile) into a throwaway DB, then scores outcomes against a
hand-labeled ground truth (data/ground_truth.json).

Metrics reported:
- Total processed / failed
- Auto-match rate  : share of *clean* invoices correctly written to ledger
- Exception recall : share of deliberately-messy invoices that got flagged
- False positive rate: clean invoices wrongly flagged (flagged-but-fine)
- Field-level extraction accuracy on ledger rows (vendor, invoice_no, total)

Nothing is cherry-picked: every mismatch is printed verbatim.

Usage:
    PYTHONPATH=backend python eval/evaluate.py [--keep-db]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

EVAL_DB = ROOT / "data" / "eval.db"

from app.config import get_settings  # noqa: E402
from app.pipeline.runner import PipelineResult, run_pipeline  # noqa: E402


def fresh_db():
    """Point the app at an isolated eval DB and create schema."""
    import app.db as dbm

    dbm.engine.dispose()
    EVAL_DB.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(EVAL_DB) + suffix).unlink(missing_ok=True)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{EVAL_DB}", connect_args={"check_same_thread": False}
    )
    dbm.engine = engine
    dbm.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    # modules that bound SessionLocal at import time must be repointed too
    import app.pipeline.runner as runner_mod

    runner_mod.SessionLocal = dbm.SessionLocal
    dbm.init_db()
    return dbm.SessionLocal  # return the factory, not an instance


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-db", action="store_true", help="keep data/eval.db for inspection")
    args = ap.parse_args()

    settings = get_settings()
    if not settings.llm_api_key:
        print("ERROR: LLM_API_KEY is required to run live evaluation.\n"
              "Copy .env.example to .env and set your key.")
        sys.exit(1)

    truth = json.loads((ROOT / "data" / "ground_truth.json").read_text())
    Session = fresh_db()

    # ---- run the real pipeline over every sample ----
    results: dict[str, dict] = {}
    print(f"Processing {len(truth)} samples through the live pipeline...\n")
    for item in truth:
        path = ROOT / "data" / "samples" / item["file"]
        db = Session()
        try:
            res = run_pipeline(db, path, item["file"], source="eval", telegram_user_id="eval")
        finally:
            db.close()
        results[item["file"]] = {
            "status": res.status,
            "reason": res.reason,
            "ledger_row": res.ledger_row(),
        }
        mark = {"ledger": "+", "exception": "!"}[res.status] if res.status in ("ledger", "exception") else "x"
        print(f"  [{mark}] {item['file']}: {res.status}"
              + (f"/{res.reason}" if res.reason else ""))

    # ---- score ----
    tp_match = fp_flag = fn_miss = tn = n_failed = 0
    field_hits = {"vendor": 0, "invoice_no": 0, "total": 0}
    field_total = 0
    mismatches: list[str] = []

    n_clean = sum(1 for t in truth if t["expected"] == "ledger")
    n_messy = len(truth) - n_clean

    for item in truth:
        got = results[item["file"]]
        expected_ledger = item["expected"] == "ledger"

        if got["status"] == "failed":
            n_failed += 1
            mismatches.append(f"FAILED  {item['file']} (pipeline error)")
            continue

        if expected_ledger:
            row = got["ledger_row"]
            if got["status"] == "ledger":
                tp_match += 1
                field_total += 1
                for f in field_hits:
                    want = round(item[f], 2) if isinstance(item[f], float) else str(item[f])
                    have = round(row[f], 2) if isinstance(row.get(f), float) else str(row.get(f))
                    if want == have:
                        field_hits[f] += 1
                    else:
                        mismatches.append(
                            f"FIELD   {item['file']}: {f} expected {want!r}, got {have!r}"
                        )
            else:
                fp_flag += 1
                mismatches.append(
                    f"FALSE-P {item['file']}: wrongly flagged {got['reason']} — {got.get('detail', '')}"
                )
        else:  # messy invoice
            if got["status"] == "exception":
                tn += 1
                if got["reason"] != item["expected_reason"]:
                    mismatches.append(
                        f"REASON  {item['file']}: expected flag {item['expected_reason']}, "
                        f"got {got['reason']}"
                    )
            else:
                fn_miss += 1
                mismatches.append(
                    f"MISSED  {item['file']}: slipped into ledger but was meant to be flagged "
                    f"({item['expected_reason']})"
                )

    # ---- report ----
    auto_match_rate = tp_match / n_clean if n_clean else 0
    exc_recall = tn / n_messy if n_messy else 0
    fp_rate = fp_flag / n_clean if n_clean else 0

    print("\n" + "=" * 64)
    print("LEDGERLOOP PIPELINE EVALUATION REPORT")
    print("=" * 64)
    print("Dataset: synthetic Indian GST invoices (machine-readable PDFs + text")
    print("files) with deliberately planted errors — NOT scanned photo OCR.")
    print(f"Structuring model: {settings.llm_provider} / {settings.llm_model}")
    print(f"Samples processed          : {len(truth)}")
    print(f"Pipeline failures          : {n_failed}")
    print("-" * 64)
    print(f"Clean invoices (should pass): {n_clean}")
    print(f"  Auto-matched to ledger    : {tp_match}  ({auto_match_rate:.1%})")
    print(f"  FALSE POSITIVES (flagged but fine): {fp_flag}  ({fp_rate:.1%} FP rate)")
    print("-" * 64)
    print(f"Messy invoices (should flag): {n_messy}")
    print(f"  Correctly flagged         : {tn}  ({exc_recall:.1%} exception recall)")
    print(f"  MISSED (slipped through)  : {fn_miss}")
    print("-" * 64)
    if field_total:
        print("Extraction field accuracy on matched rows:")
        for f, hits in field_hits.items():
            print(f"  {f:<12}: {hits}/{field_total}  ({hits / field_total:.1%})")
    print("=" * 64)

    if mismatches:
        print(f"\nMISMATCH DETAILS ({len(mismatches)}) — nothing hidden:")
        for m in mismatches:
            print(f"  - {m}")
    else:
        print("\nAll outcomes matched ground truth exactly.")

    if not args.keep_db:
        EVAL_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
