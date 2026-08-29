"""Generate a synthetic Indian-GST invoice dataset.

60 invoices total:
- 48 clean, well-formed invoices (expected: auto-matched into ledger)
- 12 deliberately messy ones (expected: exceptions):
  * 2 duplicates of earlier clean invoices
  * 2 invalid GSTINs (digit/letter typos)
  * 2 missing GSTIN
  * 3 tax mismatches beyond the Rs.1 tolerance
  * 1 unreadable date
  * 1 missing invoice number
  * 1 near-duplicate (same vendor+invoice_no but different amount -> still DUPLICATE)

Outputs PDFs (+ a few .txt for variety) in data/samples/ and a hand-authored
ground-truth label file at data/ground_truth.json.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
if not (Path(__file__).resolve().parent.parent / "backend" / "app").exists():
    # In the backend container the app package lives at the repo root (/app),
    # so fall back to uploading the parent dir (which contains app/).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gstin import gstin_checksum_char

from fpdf import FPDF


def make_gstin(state: str, pan: str, entity: str) -> str:
    """Build a checksum-valid GSTIN."""
    prefix = f"{state}{pan}{entity}Z"
    assert len(prefix) == 14
    return prefix + gstin_checksum_char(prefix)


VENDORS = [
    ("Sharma Kirana Stores", make_gstin("27", "SHKPS1234A", "1"), "groceries"),
    ("Gupta Electronics Pvt Ltd", make_gstin("07", "GUPEL5678B", "2"), "electronics"),
    ("Meena Fabrics & Tailors", make_gstin("24", "MEENF9012C", "3"), "apparel"),
    ("Patel Hardware Mart", make_gstin("24", "PATEH3456D", "1"), "hardware"),
    ("Bangalore Stationery House", make_gstin("29", "BANGS7890E", "5"), "stationery"),
    ("Sunrise Pharma Distributors", make_gstin("27", "SUNRP2345F", "6"), "pharma"),
    ("Chennai Food Court Supplies", make_gstin("33", "CHENF6789G", "7"), "food_services"),
    ("Delhi Mobile Point", make_gstin("07", "DELHM0123H", "8"), "electronics"),
]

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
GROUND_TRUTH = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"

random.seed(42)

GST_RATES = [0.05, 0.12, 0.18]

# Per-category HSN/SAC codes (4-digit) used to populate demo invoices so the
# HSN validation + HSN-wise summary paths have real data to work with.
HSN_BY_CATEGORY = {
    "groceries": "1006",
    "electronics": "8517",
    "apparel": "5210",
    "hardware": "8205",
    "stationery": "4820",
    "pharma": "3004",
    "food_services": "9963",
    "other": "9988",
}


def make_invoice_no(rng: random.Random, prefix: str, n: int) -> str:
    return f"{prefix}/{rng.randint(2025, 2025)}/{n:04d}"


def state_name(code: str) -> str:
    """2-digit GST state code -> full state name (for place_of_supply)."""
    from app.gst_states import STATE_CODES
    return STATE_CODES.get(code.zfill(2), code)


def build_invoice_fields(vendor_info, rng: random.Random, seq: int) -> dict:
    name, gstin, category = vendor_info
    taxable = round(rng.uniform(500, 25000), 2)
    rate = rng.choice(GST_RATES)
    cgst = round(taxable * rate / 2, 2)
    sgst = round(taxable * rate / 2, 2)
    total = round(taxable + cgst + sgst, 2)
    month = rng.choice(["2025-06"])
    day = rng.randint(1, 28)
    pos_code = str(gstin)[:2]
    return {
        "vendor": name,
        "gstin": gstin,
        "invoice_no": make_invoice_no(rng, "".join(w[0] for w in name.split()[:2]).upper(), seq),
        "date": f"{month}-{day:02d}",
        "taxable_value": taxable,
        "cgst": cgst,
        "sgst": sgst,
        "igst": 0.0,
        "total": total,
        "category": category,
        "hsn_code": HSN_BY_CATEGORY.get(category, "9988"),
        "place_of_supply": f"{pos_code}-{state_name(pos_code)}",
    }


def render_pdf(inv: dict, out_path: Path, overrides: dict | None = None) -> None:
    """Render a machine-readable (text-based) PDF invoice."""
    inv = {**inv, **(overrides or {})}
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.cell(0, 10, text="TAX INVOICE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("helvetica", size=11)
    rows = [
        ("Vendor", inv["vendor"]),
        ("GSTIN", inv["gstin"]),
        ("Invoice No", inv["invoice_no"]),
        ("Date", inv["date_display"] if "date_display" in inv else inv["date"]),
        ("Category", inv["category"]),
        ("Description", f"Goods/services - {inv['category']}"),
        ("Taxable Value (Rs)", f"{inv['taxable_value']:.2f}"),
        ("CGST (Rs)", f"{inv['cgst']:.2f}"),
        ("SGST (Rs)", f"{inv['sgst']:.2f}"),
        ("IGST (Rs)", f"{inv['igst']:.2f}"),
        ("Total Amount (Rs)", f"{inv['total']:.2f}"),
        ("HSN Code", inv["hsn_code"]),
        ("Place of Supply", inv["place_of_supply"]),
    ]
    for label, value in rows:
        v = "" if value is None else str(value)
        pdf.cell(55, 8, text=label, border=1)
        pdf.cell(0, 8, text=v, border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("helvetica", size=9)
    pdf.multi_cell(0, 5, text="Thank you for your business. This is a computer generated invoice.")
    pdf.output(str(out_path))


def render_txt(inv: dict, out_path: Path, overrides: dict | None = None) -> None:
    inv = {**inv, **(overrides or {})}
    lines = [
        "TAX INVOICE",
        "=" * 46,
        f"Vendor      : {inv['vendor']}",
        f"GSTIN       : {inv.get('gstin') or ''}",
        f"Invoice No  : {inv['invoice_no']}",
        f"Date        : {inv.get('date_display', inv['date'])}",
        "-" * 46,
        f"Taxable Value : Rs. {inv['taxable_value']:,.2f}",
        f"CGST          : Rs. {inv['cgst']:,.2f}",
        f"SGST          : Rs. {inv['sgst']:,.2f}",
        f"IGST          : Rs. {inv['igst']:,.2f}",
        f"TOTAL AMOUNT  : Rs. {inv['total']:,.2f}",
        f"HSN Code      : {inv.get('hsn_code') or ''}",
        f"Place of Supply : {inv.get('place_of_supply') or ''}",
        "-" * 46,
        "Computer generated invoice.",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    generate()


def generate(samples_dir: Path | None = None) -> Path:
    """Generate the 60-sample dataset and ground truth into samples_dir.

    Returns samples_dir. Callable programmatically so the backend can seed a
    demo database on startup.
    """
    out_dir = samples_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():
        old.unlink()

    truth: list[dict] = []
    seq = 100

    # --- 48 clean invoices ---
    clean_specs = []
    for i in range(48):
        info = VENDORS[i % len(VENDORS)]
        rng = random.Random(1000 + i)
        inv = build_invoice_fields(info, rng, seq)
        seq += rng.randint(1, 9)
        clean_specs.append(inv)

        fname = f"clean_{i + 1:02d}_{info[0].split()[0].lower()}.{'txt' if i % 4 == 0 else 'pdf'}"
        path = out_dir / fname
        if fname.endswith(".txt"):
            render_txt(inv, path)
        else:
            render_pdf(inv, path)

        truth.append({
            "file": fname,
            "expected": "ledger",
            "expected_reason": None,
            "vendor": inv["vendor"],
            "invoice_no": inv["invoice_no"],
            "total": inv["total"],
        })

    # --- 12 messy invoices ---
    messy_idx = 0

    def messy_name(kind: str) -> tuple[str, Path]:
        nonlocal messy_idx
        messy_idx += 1
        fname = f"messy_{messy_idx:02d}_{kind}.txt"
        return fname, out_dir / fname

    # 1-2: exact duplicates of clean_01 and clean_05
    for src_i in (0, 4):
        inv = clean_specs[src_i]
        fname, path = messy_name("duplicate")
        render_txt(inv, path)
        truth.append({
            "file": fname,
            "expected": "exception",
            "expected_reason": "DUPLICATE",
            "note": f"duplicate of clean_{src_i + 1:02d}",
            "vendor": inv["vendor"],
            "invoice_no": inv["invoice_no"],
            "total": inv["total"],
        })

    # 3-4: invalid GSTIN (typo'd char)
    for pos_note in ("digit_swapped", "bad_state_code"):
        base = VENDORS[2 if pos_note == "digit_swapped" else 5]
        rng = random.Random(hash(pos_note) % 9999)
        inv = build_invoice_fields(base, rng, seq); seq += 3
        bad_gstin = list(inv["gstin"])
        if pos_note == "digit_swapped":
            bad_gstin[13] = "X"  # invalid character at check-position
        else:
            bad_gstin[0] = "9"   # invalid state code
        inv["gstin"] = "".join(bad_gstin)
        fname, path = messy_name("invalid_gstin")
        render_txt(inv, path)
        truth.append({
            "file": fname, "expected": "exception",
            "expected_reason": "INVALID_GSTIN",
            "vendor": inv["vendor"], "invoice_no": inv["invoice_no"], "total": inv["total"],
        })

    # 5-6: missing GSTIN entirely
    for i in (6, 7):
        rng = random.Random(2000 + i)
        inv = build_invoice_fields(VENDORS[i], rng, seq); seq += 2
        del inv["gstin"]
        fname, path = messy_name("missing_gstin")
        render_txt(inv, path)
        truth.append({
            "file": fname, "expected": "exception",
            "expected_reason": "GSTIN_MISSING",
            "vendor": inv["vendor"], "invoice_no": inv["invoice_no"], "total": inv["total"],
        })

    # 7-9: tax mismatch beyond Rs.1 tolerance
    for delta in (150.00, 12.75, 2.50):
        rng = random.Random(int(delta * 10))
        inv = build_invoice_fields(VENDORS[rng.randint(0, 7)], rng, seq); seq += 4
        inv["total"] = round(inv["taxable_value"] + inv["cgst"] + inv["sgst"] + delta, 2)
        fname, path = messy_name("tax_mismatch")
        render_txt(inv, path)
        truth.append({
            "file": fname, "expected": "exception",
            "expected_reason": "TAX_MISMATCH",
            "vendor": inv["vendor"], "invoice_no": inv["invoice_no"], "total": inv["total"],
        })

    # 10: unreadable date
    rng = random.Random(777)
    inv = build_invoice_fields(VENDORS[3], rng, seq); seq += 1
    inv["date_display"] = "sometime last week"
    inv["date"] = None
    fname, path = messy_name("bad_date")
    t = inv.copy(); t.pop("date")
    body = [
        "TAX INVOICE",
        f"Vendor      : {t['vendor']}",
        f"GSTIN       : {t['gstin']}",
        f"Invoice No  : {t['invoice_no']}",
        "Date        : sometime last week",
        f"Taxable Value : Rs. {t['taxable_value']:,.2f}",
        f"CGST          : Rs. {t['cgst']:,.2f}",
        f"SGST          : Rs. {t['sgst']:,.2f}",
        f"TOTAL AMOUNT  : Rs. {t['total']:,.2f}",
    ]
    path.write_text("\n".join(body), encoding="utf-8")
    truth.append({
        "file": fname, "expected": "exception",
        "expected_reason": "BAD_DATE",
        "vendor": inv["vendor"], "invoice_no": inv["invoice_no"], "total": inv["total"],
    })

    # 11: missing invoice number
    rng = random.Random(888)
    inv = build_invoice_fields(VENDORS[4], rng, seq); seq += 1
    body = [
        "TAX INVOICE",
        f"Vendor      : {inv['vendor']}",
        f"GSTIN       : {inv['gstin']}",
        "Invoice No  : ",
        f"Date        : {inv['date']}",
        f"Taxable Value : Rs. {inv['taxable_value']:,.2f}",
        f"CGST          : Rs. {inv['cgst']:,.2f}",
        f"SGST          : Rs. {inv['sgst']:,.2f}",
        f"TOTAL AMOUNT  : Rs. {inv['total']:,.2f}",
    ]
    fname, path = messy_name("missing_invoice_no")
    path.write_text("\n".join(body), encoding="utf-8")
    truth.append({
        "file": fname, "expected": "exception",
        "expected_reason": "EXTRACTION_INCOMPLETE",
        "vendor": inv["vendor"], "invoice_no": None, "total": inv["total"],
    })

    # 12: near-duplicate (same vendor+invoice_no as an existing clean one, different total)
    inv = dict(clean_specs[10])
    inv["total"] = round(inv["total"] * 2, 2)  # same pair keys, different money
    fname, path = messy_name("near_duplicate")
    render_txt(inv, path)
    truth.append({
        "file": fname, "expected": "exception",
        "expected_reason": "DUPLICATE",
        "note": "same vendor+invoice_no as clean_11, different amount",
        "vendor": inv["vendor"], "invoice_no": inv["invoice_no"], "total": inv["total"],
    })

    GROUND_TRUTH.write_text(json.dumps(truth, indent=2), encoding="utf-8")

    n_ledger = sum(1 for t in truth if t["expected"] == "ledger")
    print(f"Generated {len(truth)} samples in {out_dir}")
    print(f"  expected auto-match: {n_ledger}, expected exceptions: {len(truth) - n_ledger}")
    print(f"Ground truth: {GROUND_TRUTH}")

    return out_dir


if __name__ == "__main__":
    main()
