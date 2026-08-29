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

# HSN/SAC codes are numeric; valid lengths are 4, 6 or 8 digits.
_HSN_RE = re.compile(r"^\d{4,8}$")


def valid_hsn(value: Optional[str]) -> bool:
    if not value:
        return False
    v = str(value).strip()
    return len(v) in (4, 6, 8) and _HSN_RE.fullmatch(v) is not None

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d")


def normalize_vendor(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]", "", vendor.lower())


def parse_date(value: Optional[str]) -> Optional[str]:
    """Return YYYY-MM-DD or None."""
    if not value:
        return None
    v = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
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
    }
    return row, None, ""
