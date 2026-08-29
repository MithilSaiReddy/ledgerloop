"""Step 2 of the pipeline: Markdown text -> structured invoice JSON via LLM.

Provider-agnostic: any OpenAI-compatible chat-completions endpoint works
(Mistral by default, Groq/Llama 3.3 supported). Strict JSON-only extraction
with one retry, then StructureError.
"""

import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ["vendor", "invoice_no", "date", "taxable_value", "total"]

SYSTEM_PROMPT = """You are an invoice data extraction engine for Indian GST invoices.
Extract the fields below from the given invoice text. Respond with ONE JSON object and nothing else.
Rules:
- Numbers are plain floats in INR, no commas, no currency symbols.
- cgst + sgst are for intra-state supplies; igst for inter-state. Use 0 when absent.
- date must be YYYY-MM-DD. Convert formats like 05/03/2025 (DD/MM/YYYY assumed for Indian invoices).
- category: one of groceries, electronics, apparel, hardware, stationery, pharma, food_services, other.
- hsn_code: the 4/6/8-digit HSN/SAC code shown on the invoice line, e.g. "5210" or "8517". null if absent.
- place_of_supply: the 2-digit GST state code and/or state name where the goods are supplied (e.g. "27-Maharashtra", "Maharashtra"). null if absent.
- type: is the shop the BUYER or the SELLER on this bill? Use "purchase" when the shop
  is buying (vendor/seller party is someone else, e.g. a supplier bill), "sale" when the
  shop issued the bill to its customer. Judge from Bill To / Ship To / seller details.
- If a field genuinely cannot be found, use null for it. Do NOT guess numbers.
Schema:
{"type": "purchase"|"sale"|null, "vendor": str|null, "party_name": str|null, "gstin": str|null,
 "invoice_no": str|null, "date": str|null, "taxable_value": float|null, "cgst": float|null,
 "sgst": float|null, "igst": float|null, "total": float|null, "category": str|null,
 "hsn_code": str|null, "place_of_supply": str|null}"""


class StructureError(Exception):
    pass


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    s = re.sub(r"[₹,\s]", "", str(value))
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def demo_structure(markdown_text: str) -> dict[str, Any]:
    """Offline, deterministic extractor used in demo mode when no LLM key is set.

    Parses the machine-readable invoice text produced by generator.py /
    markitdown. Supports two layouts:
      * inline  — "Label : value" on a single line (the .txt samples)
      * columnar — fpdf's output, where all labels are listed first and the
        values follow in the same order on subsequent lines (the .pdf samples)

    Output flows through normalize_extraction so the rest of the pipeline
    behaves identically. Never touches the network or a paid LLM.
    """
    lines = [ln.strip() for ln in (markdown_text or "").splitlines()]

    def inline(labels: list[str], num: bool = False) -> str | None:
        """Look for 'Label : value' where value is on the same line."""
        for ln in lines:
            for lab in labels:
                m = re.search(re.escape(lab), ln, re.IGNORECASE)
                if not m:
                    continue
                rest = ln[m.end():].lstrip(": \t-").strip()
                if rest:
                    if num:
                        n = re.search(r"[0-9][0-9.,]*", rest)
                        if n:
                            return n.group(0)
                    else:
                        return rest
        return None

    # The .pdf samples are columnar (labels, then values in order). Use that
    # only when the inline layout never works, so genuinely-missing inline
    # fields (e.g. an absent invoice_no on a .txt) stay missing.
    vendor_inline = inline(["Vendor"])
    vendor = vendor_inline or _col(lines, "TAX INVOICE", 0)
    if not vendor:
        return normalize_extraction({})
    use_col = vendor_inline is None

    gstin = inline(["GSTIN"]) or (use_col and _col(lines, "TAX INVOICE", 1)) or None
    invoice_no = inline(["Invoice No", "INVOICE NO", "Invoice #", "Invoice no"]) or (
        use_col and _col(lines, "TAX INVOICE", 2)) or None
    date = inline(["Date"]) or (use_col and _col(lines, "TAX INVOICE", 3)) or None

    taxable = inline(["Taxable"], num=True) or _amount_after(lines, ["Taxable Value", "Taxable"])
    total = inline(["TOTAL AMOUNT", "Grand Total", "TOTAL"], num=True) or _amount_after(
        lines, ["Total Amount", "TOTAL AMOUNT"])

    cgst = inline(["CGST"], num=True)
    sgst = inline(["SGST"], num=True)
    igst = inline(["IGST"], num=True)
    if use_col and not (cgst and sgst and igst):
        # Columnar PDF: CGST/SGST/IGST list their labels together, then the
        # three values follow in order.
        trio = _amount_trio(lines)
        if trio:
            cgst = cgst or trio[0]
            sgst = sgst or trio[1]
            igst = igst or trio[2]

    raw = {
        "type": None,
        "vendor": vendor,
        "gstin": (gstin.upper() if gstin else None),
        "invoice_no": invoice_no,
        "date": date,
        "taxable_value": taxable,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total": total,
        "category": None,
        "hsn_code": inline(["HSN Code", "HSN"]),
        "place_of_supply": inline(["Place of Supply", "Place of supply", "Place Of Supply"]),
    }
    return normalize_extraction(raw)


def _col(lines: list[str], marker: str, idx: int) -> str | None:
    """Columnar header parse: values appear after `marker` after the label block."""
    try:
        mi = next(i for i, ln in enumerate(lines) if ln.upper().startswith(marker))
    except StopIteration:
        return None
    vals = [ln for ln in lines[mi + 1:] if ln]
    return vals[idx] if idx < len(vals) else None


def _amount_after(lines: list[str], labels: list[str]) -> str | None:
    """First money number on/after the first matching label line."""
    for i, ln in enumerate(lines):
        if any(ln.upper().startswith(lab.upper()) for lab in labels):
            for cand in lines[i:]:
                m = re.search(r"[0-9][0-9.,]*", cand)
                if m:
                    return m.group(0)
            return None
    return None


def _amount_trio(lines: list[str]) -> list[str] | None:
    """Columnar PDF: after the CGST/SGST/IGST label block, the next three
    money numbers are cgst, sgst, igst in order."""
    idxs = [i for i, ln in enumerate(lines)
            if any(re.fullmatch(r"(?:CGST|SGST|IGST)(?: \(Rs\))?", ln, re.IGNORECASE)
                   for _ in [ln])]
    if not idxs:
        return None
    start = max(idxs)
    nums = [m.group(0) for ln in lines[start + 1:]
            if (m := re.search(r"[0-9][0-9.,]*", ln))]
    return (nums[:3] if len(nums) >= 3 else None)


def normalize_extraction(raw: dict[str, Any]) -> dict[str, Any]:
    inv_type = str(raw.get("type") or "").strip().lower()
    out = {
        "type": inv_type if inv_type in ("purchase", "sale") else None,
        "vendor": (str(raw["vendor"]).strip() if raw.get("vendor") else None),
        "party_name": (str(raw["party_name"]).strip() if raw.get("party_name") else None),
        "gstin": (str(raw["gstin"]).strip().upper() if raw.get("gstin") else None),
        "invoice_no": (str(raw["invoice_no"]).strip() if raw.get("invoice_no") else None),
        "date": (str(raw["date"]).strip() if raw.get("date") else None),
        "category": (str(raw["category"]).strip().lower() if raw.get("category") else "uncategorized"),
        "hsn_code": (str(raw["hsn_code"]).strip() if raw.get("hsn_code") else None),
        "place_of_supply": (str(raw["place_of_supply"]).strip() if raw.get("place_of_supply") else None),
    }
    for k in ("taxable_value", "cgst", "sgst", "igst", "total"):
        out[k] = _coerce_float(raw.get(k))
    for k in ("cgst", "sgst", "igst"):
        if out[k] is None:
            out[k] = 0.0
    return out


def missing_required_fields(inv: dict[str, Any]) -> list[str]:
    missing = []
    for f in REQUIRED_FIELDS:
        v = inv.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(f)
    return missing


def _extract_json(content: str) -> dict[str, Any]:
    """Parse JSON from a model response, tolerating ```json fences."""
    content = content.strip()
    fence = re.match(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
    if fence:
        content = fence.group(1)
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    return json.loads(content)


def llm_structure(
    markdown_text: str,
    api_key: str,
    model: str = "mistral-small-latest",
    base_url: str = "https://api.mistral.ai/v1",
) -> dict[str, Any]:
    """Call an OpenAI-compatible LLM to turn invoice Markdown into structured JSON."""
    last_err: Exception | None = None

    for attempt in range(2):
        try:
            resp = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Invoice text:\n\n{markdown_text[:12000]}"},
                    ],
                    "max_tokens": 600,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"] or ""
            raw = _extract_json(content)
            return normalize_extraction(raw if isinstance(raw, dict) else {})
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("llm_structure attempt %d failed: %s", attempt + 1, exc)

    raise StructureError(f"LLM extraction failed: {last_err}")
