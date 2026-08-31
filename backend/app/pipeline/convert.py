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


def _preprocess_for_ocr(img: "Image.Image") -> "Image.Image":
    """Grayscale + contrast + upscale so tesseract sees a cleaner image.

    Phone photos of paper invoices are often low-contrast, angled and shot at
    low DPI. Upscaling 2x keeps letterforms intact for tesseract which expects
    ~300 DPI, and autocontrast separates the ink from the paper.
    """
    from PIL import Image, ImageOps

    gray = img.convert("L")
    gray = ImageOps.autocontrast(gray, cutoff=2)
    scale = 2
    w, h = gray.size
    scale = 2 if max(w, h) < 2400 else 1  # huge scans don't need upscaling
    if scale > 1:
        gray = gray.resize((w * scale, h * scale), Image.LANCZOS)
    return gray


def _convert_with_tesseract_preprocessed(path: Path, psm: str) -> str:
    """OCR the image with preprocessing, trying the given page-seg mode."""
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        processed = _preprocess_for_ocr(img)
        return pytesseract.image_to_string(processed, config=f"--psm {psm}")


def _upscale_image(path: str | Path, min_dim: int = 1600) -> "Image.Image":
    """Cheap 2x upscale for low-res phone photos before sending to OCR.

    Telegram downscales sent photos to ~1280px; Mistral OCR reads small text
    better when the image is scaled up in clean LANCZOS.
    """
    from PIL import Image

    with Image.open(path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        if min(img.size) >= min_dim:
            img = img.copy()
        else:
            scale = 2
            img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        return img


def ocr_image_convert(path: str | Path, api_key: str,
                      base_url: str = "https://api.mistral.ai/v1",
                      model: str = "mistral-ocr-latest") -> str:
    """OCR the image with Mistral's vision-backed document OCR API.

    Returns the extracted Markdown (tables preserved). Far more accurate on
    real phone photos than tesseract. Raises on API/HTTP failure so the caller
    can fall back to the offline path.
    """
    import base64
    import io

    import httpx

    upscaled = _upscale_image(path)
    buf = io.BytesIO()
    upscaled.save(buf, format="JPEG", quality=95)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    resp = httpx.post(
        f"{base_url.rstrip('/')}/ocr",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "document": {"type": "image_url", "image_url": data_url},
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    pages = resp.json().get("pages") or []
    if not pages:
        raise RuntimeError(f"Mistral OCR returned no pages for {Path(path).name}")
    return pages[0].get("markdown") or ""


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
        # Weak output on a scanned image -> try tesseract (with preprocessing)
        # across a couple of page-segmentation modes, keep the best result.
        # Some handwritten shops bills legitimately lack GST keywords, so a
        # score of 0 must NOT disqualify a non-empty tesseract result; score
        # only decides between candidates.
        best_text = ""
        best_score = -1
        for psm in ("6", "3"):
            try:
                cand = _convert_with_tesseract_preprocessed(p, psm)
                score = _invoice_signal_score(cand)
                if cand.strip() and (
                    score > best_score
                    or (score == best_score and len(cand) > len(best_text))
                ):
                    best_text, best_score = cand, score
            except Exception as exc:  # noqa: BLE001
                logger.warning("pytesseract (psm %s) failed on %s: %s", psm, p.name, exc)

        if best_text:
            return best_text, "pytesseract"
        if text:
            return text, "markitdown+pytesseract"
        raise RuntimeError(f"could not extract any text from {p.name}")

    if not text and ext not in IMAGE_EXTS:
        raise RuntimeError(f"could not extract any text from {p.name}")

    return text, "markitdown"
