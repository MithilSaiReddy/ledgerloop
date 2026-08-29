"""Step 1 of the pipeline: file -> clean Markdown text.

Strategy:
- PDFs / docx / xlsx / html: MarkItDown.
- Images (scanned invoice photos): MarkItDown first, pytesseract as fallback.
  We score MarkItDown's output with a cheap "invoice signal" heuristic; if it
  looks like OCR junk we retry with pytesseract and keep whichever scores higher.
"""

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

# Tokens that should appear in any readable Indian GST invoice.
_SIGNAL_TOKENS = [
    "invoice", "gst", "gstin", "total", "taxable",
    "cgst", "sgst", "igst", "rupee", "rs.", "₹",
]


def _invoice_signal_score(text: str) -> int:
    lowered = text.lower()
    hits = sum(1 for tok in _SIGNAL_TOKENS if tok in lowered)
    alnum_ratio = sum(c.isalnum() for c in text) / max(len(text), 1)
    # Long garbage strings from bad OCR dilute the alnum ratio oddly high or low;
    # the token hit count is the primary signal.
    return hits


def _convert_with_markitdown(path: Path) -> str:
    from markitdown import MarkItDown

    md = MarkItDown()
    result = md.convert(str(path))
    return result.text_content or ""


def _convert_with_tesseract(path: Path) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        return pytesseract.image_to_string(img)


def markitdown_convert(path: str | Path) -> tuple[str, str]:
    """Convert an invoice file to Markdown text.

    Returns (text, converter_used) where converter_used is one of
    'markitdown', 'pytesseract', 'markitdown+pytesseract'.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"invoice file not found: {p}")

    ext = p.suffix.lower()
    try:
        text = _convert_with_markitdown(p)
        markitdown_ok = _invoice_signal_score(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("markitdown failed on %s: %s", p.name, exc)
        text, markitdown_ok = "", -1

    if ext in IMAGE_EXTS and markitdown_ok < 3:
        # Weak output on a scanned image -> try tesseract, keep the better one.
        try:
            tess_text = _convert_with_tesseract(p)
            if _invoice_signal_score(tess_text) > markitdown_ok:
                return tess_text, "pytesseract"
            if text:
                return text, "markitdown+pytesseract"
            return tess_text, "pytesseract"
        except Exception as exc:  # noqa: BLE001
            logger.warning("pytesseract failed on %s: %s", p.name, exc)

    if not text and ext not in IMAGE_EXTS:
        raise RuntimeError(f"could not extract any text from {p.name}")

    return text, "markitdown"
