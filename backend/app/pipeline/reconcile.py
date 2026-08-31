"""Step 3 of the pipeline: decide ledger vs exception.

Pure functions — fully unit-testable without network or DB.
"""

import datetime as dt
import re
from typing import Any, Optional

from app.gst_states import state_code_from
from app.gstin import gstin_valid
from app.pipeline.structure import missing_required_fields

TOLERANCE_INR = 1.0

REASONS = {
    "DUPLICATE": "Duplicate invoice (same vendor + invoice_no already in ledger)",
    "INVALID_GSTIN": "GSTIN failed format validation",
    "GSTIN_MISSING": "GSTIN not found on invoice",
    "TAX_MISMATCH": "taxable_value + taxes does not equal total",
    "HSN_MISSING": "HSN/SAC code missing or invalid, needed for GST filing",
    "TAX_TREATMENT_MISMATCH": "tax treatment doesn't match intra/inter-state rules",
    "EXTRACTION_INCOMPLETE": "Required fields could not be extracted",
    "BAD_DATE": "Invoice date missing or unparseable",
}

# Default GST rate (%) applied to a sales bill that prints no tax split.
# GST 2.0 (56th GST Council, effective 22 Sep 2025) collapsed India's slabs to
# two — 5% (merit) and 18% (standard). The owner picks ONE shop-wide default in
# Settings (a "business type" quick-pick that stays editable). The bill category
# below is only a fallback when the owner hasn't set their default yet.
CATEGORY_GST_RATE: dict[str, float] = {
    "groceries": 5.0,
    "apparel": 5.0,
    "electronics": 18.0,
    "hardware": 18.0,
    "stationery": 5.0,
    "pharma": 5.0,
    "food_services": 5.0,
    "other": 18.0,
}

# Absolute last-resort standard rate when neither the owner's default nor a
# known category yields a rate.
STANDARD_GST_RATE = 18.0

# HSN/SAC codes are numeric; valid lengths are 4, 6 or 8 digits.
_HSN_RE = re.compile(r"^\d{4,8}$")


def valid_hsn(value: Optional[str]) -> bool:
    if not value:
        return False
    v = str(value).strip()
    return len(v) in (4, 6, 8) and _HSN_RE.fullmatch(v) is not None

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d")
_YY_FORMATS = ("%d/%m/%y", "%d-%m-%y", "%d.%m.%y")


def _current_year() -> int:
    return dt.date.today().year


def _resolve_year(yy: int) -> int:
    """Map a two-digit year to the century that makes the date 'relevant'.

    Indian invoices carry short years like `9/26`. Pick the century whose year
    is closest to today, so `26` -> 2026, `99` -> 1999 — never 1926 or 2099 for
    a current bill.
    """
    now = _current_year()
    return min((1900 + yy, 2000 + yy), key=lambda y: abs(y - now))


def normalize_vendor(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]", "", vendor.lower())


def parse_date(value: Optional[str]) -> Optional[str]:
    """Return YYYY-MM-DD or None.

    Accepts ISO dates, Indian DD/MM formatting (slash, dash or dot), and
    two-digit years resolved to the relevant recent century (`25/9/26` ->
    2026-09-25).
    """
    if not value:
        return None
    v = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    for fmt in _YY_FORMATS:
        try:
            parsed = dt.datetime.strptime(v, fmt)
        except ValueError:
            continue
        # strptime's %y uses a fixed 1969/1970 pivot that's wrong for current
        # invoices; resolve the short trailing year against today instead.
        m = re.search(r"(\d{1,2})$", v)
        if m is None:
            continue
        return parsed.replace(year=_resolve_year(int(m.group(1)))).strftime("%Y-%m-%d")
    return None


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(re.sub(r"[₹,\s]", "", str(value)))
    except ValueError:
        return None


def check_tax_sum(inv: dict[str, Any]) -> bool:
    taxable = _f(inv.get("taxable_value"))
    total = _f(inv.get("total"))
    if taxable is None or total is None:
        return False
    tax = (_f(inv.get("cgst")) or 0.0) + (_f(inv.get("sgst")) or 0.0) + (_f(inv.get("igst")) or 0.0)
    return abs((taxable + tax) - total) <= TOLERANCE_INR


def _is_interstate(owner: dict[str, Any], inv: dict[str, Any]) -> bool:
    """True when the owner's state and the supply place differ (inter-state)."""
    owner_state = (owner.get("state_code") or "").strip() or None
    pos_state = state_code_from(inv.get("place_of_supply"))
    return bool(owner_state and pos_state and pos_state != owner_state)


def _shop_rate(owner: dict[str, Any], category: str | None) -> tuple[float, str]:
    """The one shop-wide rate for a no-tax sale.

    Order: the owner's single default (Settings, key "default") -> the bill
    category default -> the 18% standard rate. Returns (rate, source_label)
    so the tax_note stays transparent.
    """
    owner_rates = owner.get("tax_rates") or {}
    default = owner_rates.get("default")
    if default is not None:
        return float(default), "your default rate"
    cat = str(category or "").strip().lower()
    if cat and CATEGORY_GST_RATE.get(cat) is not None:
        return float(CATEGORY_GST_RATE[cat]), "bill category default"
    return STANDARD_GST_RATE, "standard rate"


def apply_tax_fallback(
    inv: dict[str, Any],
    owner: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fill in CGST/SGST/IGST when the bill printed no tax split.

    Returns (working_copy, tax_note):
    - Embedded tax: `total > taxable` with zero tax lines — the difference IS the
      tax on the document, split CGST+SGST (intra) or IGST (inter). Factual.
    - Sales, GST-registered, still zero tax: derive the rate from the owner's
      single shop default (Settings), treating the lump Total as GST-INCLUSIVE:
      taxable = total / (1+r) and tax = total - taxable. Marked so the owner/CA
      sees it was derived.
    - Purchases with no tax at all: never invent a number (input credit can't be
      claimed on a guess) — return a review note only.
    """
    owner = owner or {}
    data = dict(inv)
    if any(float(data.get(k) or 0.0) != 0.0 for k in ("cgst", "sgst", "igst")):
        return data, None  # tax already present — nothing to do

    taxable = _f(data.get("taxable_value"))
    total = _f(data.get("total"))
    if taxable is None or total is None:
        return data, None

    diff = round(total - taxable, 2)

    # Embedded tax: the bill's own total exceeds its taxable sum and prints no
    # tax lines, so the gap is the GST charged. This reflects the document.
    if diff > TOLERANCE_INR:
        inter = _is_interstate(owner, data)
        if inter:
            data["igst"] = diff
            note = "tax embedded in total (no split printed) — recorded as IGST (inter-state)"
        else:
            data["cgst"] = data["sgst"] = round(diff / 2, 2)
            suffix = "verify input credit with your CA" if data.get("type") == "purchase" else "assumed intra-state CGST+SGST"
            note = f"tax embedded in total (no split printed) — {suffix}"
        return data, note

    # No tax anywhere: only worth deriving for GST-registered sales.
    if abs(diff) > TOLERANCE_INR:
        return data, None

    inv_type = str(data.get("type") or "").lower()
    if inv_type == "purchase":
        return data, "no tax shown on purchase — verify input credit with your CA"

    if not owner.get("gst_registered"):
        return data, None

    rate, rate_source = _shop_rate(owner, data.get("category"))
    if not rate or rate <= 0:
        return data, None

    # Lump Total treated as GST-INCLUSIVE: strip the tax back out.
    taxable_incl = round(total / (1 + rate / 100.0), 2)
    tax = round(total - taxable_incl, 2)
    data["taxable_value"] = taxable_incl
    inter = _is_interstate(owner, data)
    if inter:
        data["igst"] = tax
        side = "IGST (inter-state)"
    else:
        data["cgst"] = data["sgst"] = round(tax / 2, 2)
        side = "CGST+SGST"
    note = (
        f"no tax printed — derived {rate:g}% ({rate_source} for "
        f"{data.get('category') or 'uncategorized'}) {side} on GST-inclusive total"
    )
    return data, note


def _tax_treatment_check(
    *,
    cgst: float, sgst: float, igst: float,
    owner_state: Optional[str], pos_state: Optional[str], is_interstate: Optional[bool],
) -> Optional[str]:
    """Return a plain-language reason when tax split contradicts the supply type.

    - Inter-state supply (owner state != place of supply): expect IGST only.
    - Intra-state supply (same state): expect a CGST+SGST split.
    - When both owner state and place of supply are known but disagree with the
      tax split, flag it. When either is missing we only flag the gross case
      (IGST charged together with CGST/SGST), which is never valid.
    """
    has_cg = cgst != 0.0
    has_sg = sgst != 0.0
    has_ig = igst != 0.0

    # Never valid: IGST can't coexist with CGST/SGST on the same line.
    if has_ig and (has_cg or has_sg):
        return (
            "Invoice has both IGST and CGST/SGST. A supply is either intra-state "
            "(CGST+SGST) or inter-state (IGST), not both."
        )

    if is_interstate is None:
        return None

    if is_interstate:
        if has_cg or has_sg:
            return (
                "This looks like an inter-state supply, so only IGST should apply. "
                "The invoice shows CGST/SGST instead."
            )
        return None

    # Intra-state: expect the CGST+SGST split.
    if has_ig:
        return (
            "This looks like an intra-state supply (same state), so CGST+SGST should "
            "apply — but the invoice shows IGST."
        )
    if has_cg and has_sg and abs(cgst - sgst) > TOLERANCE_INR:
        return (
            "CGST and SGST should be equal for intra-state supplies, "
            f"but they read ₹{cgst:,.2f} and ₹{sgst:,.2f}."
        )
    return None


def reconcile(
    extracted: dict[str, Any],
    existing_pairs: set[tuple[str, str]],
    owner: Optional[dict[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str], str]:
    """Decide where an extracted invoice goes.

    `owner` (optional) carries the shop's GST context so the pipeline can work
    out intra- vs inter-state tax treatment: ``{"state_code", "gst_registered"}``.

    Returns (ledger_row, reason_code, detail):
    - ledger_row is a dict ready for LedgerEntry when the invoice reconciles cleanly
      (or None if it's an exception).
    - reason_code/detail explain any exception.
    """
    owner = owner or {}
    owner_state = (owner.get("state_code") or "").strip() or None

    # Fill in missing CGST/SGST/IGST before the tax-sum and tax-treatment
    # checks: embedded tax from the total, or a category-derived rate on
    # GST-registered sales that printed no tax at all.
    derived, tax_note = apply_tax_fallback(extracted, owner)
    extracted = derived

    missing = missing_required_fields(extracted)
    date = parse_date(extracted.get("date"))

    if missing:
        fields = ", ".join(missing)
        return None, "EXTRACTION_INCOMPLETE", f"missing required fields: {fields}"

    if date is None:
        return None, "BAD_DATE", f"unparseable date: {extracted.get('date')!r}"

    vendor_key = normalize_vendor(extracted["vendor"])
    pair = (vendor_key, str(extracted["invoice_no"]).strip())
    if pair in existing_pairs:
        return None, "DUPLICATE", (
            f"invoice_no {extracted['invoice_no']} from {extracted['vendor']} already exists"
        )

    gstin = (extracted.get("gstin") or "").strip().upper()
    if not gstin:
        return None, "GSTIN_MISSING", "no GSTIN present in extracted data"
    if not gstin_valid(gstin):
        return None, "INVALID_GSTIN", (
            f"GSTIN {gstin!r} fails format/checksum validation"
        )

    hsn = str(extracted.get("hsn_code") or "").strip()
    if not valid_hsn(hsn):
        return None, "HSN_MISSING", (
            "HSN/SAC code missing or invalid, needed for GST filing"
            + (f" (read {hsn!r})" if hsn else "")
        )

    items = extracted.get("items") or []
    if not isinstance(items, list):
        items = []

    if not check_tax_sum(extracted):
        tax = (_f(extracted.get("cgst")) or 0.0) + (_f(extracted.get("sgst")) or 0.0) + (
            _f(extracted.get("igst")) or 0.0
        )
        computed = round((_f(extracted["taxable_value"]) or 0) + tax, 2)
        return None, "TAX_MISMATCH", (
            f"taxable {extracted['taxable_value']} + tax {round(tax, 2)} = {computed} "
            f"but total reads {extracted['total']}"
        )

    # Intra- vs inter-state tax treatment.
    cgst, sgst, igst = _f(extracted.get("cgst")) or 0.0, _f(extracted.get("sgst")) or 0.0, \
        _f(extracted.get("igst")) or 0.0
    pos_state = state_code_from(extracted.get("place_of_supply"))
    is_interstate = None
    if owner_state and pos_state:
        is_interstate = pos_state != owner_state

    tax_reason = _tax_treatment_check(
        cgst=cgst, sgst=sgst, igst=igst,
        owner_state=owner_state, pos_state=pos_state, is_interstate=is_interstate,
    )
    if tax_reason is not None:
        return None, "TAX_TREATMENT_MISMATCH", tax_reason

    row = {
        "type": extracted.get("type") or None,
        "vendor": extracted["vendor"],
        "party_name": str(extracted.get("party_name") or extracted["vendor"]),
        "gstin": gstin,
        "invoice_no": str(extracted["invoice_no"]),
        "date": date,
        "month": date[:7],
        "taxable_value": round(_f(extracted["taxable_value"]), 2),
        "cgst": round(cgst, 2),
        "sgst": round(sgst, 2),
        "igst": round(igst, 2),
        "total": round(_f(extracted["total"]), 2),
        "category": extracted.get("category") or "uncategorized",
        "hsn_code": hsn,
        "place_of_supply": str(extracted.get("place_of_supply") or "") or None,
        "is_interstate": is_interstate,
        "tax_note": tax_note,
        "items": items,
    }
    return row, None, ""
