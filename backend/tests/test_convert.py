import httpx
import pytest
from PIL import Image

from app.pipeline.convert import IMAGE_EXTS, markitdown_convert, ocr_image_convert

MARKDOWN = """# **Vibgyor Studio**

By Prathima Reddy

Bill No: 1198
Date: 25/9/26

| SL. NO | PARTICULARS | QTY. | AMOUNT |
| --- | --- | --- | --- |
| 1. | Lining Blouse + pattern 900x2 |  | 1800 |
| 2. | Hand Embroidery |  |  |
|  | Total | 3000 |  |
"""


def make_image(tmp_path, name="invoice.jpg") -> str:
    img = Image.new("RGB", (320, 240), "white")
    path = tmp_path / name
    img.save(path)
    return str(path)


class TestOcrImageConvert:
    def test_happy_path_returns_markdown(self, tmp_path, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            assert json["model"] == "mistral-ocr-latest"
            assert json["document"]["type"] == "image_url"
            assert json["document"]["image_url"].startswith("data:image/jpeg;base64,")
            return _Response(200, {"pages": [{"markdown": MARKDOWN}]})

        monkeypatch.setattr(httpx, "post", fake_post)
        text = ocr_image_convert(make_image(tmp_path), api_key="k")
        assert "Vibgyor Studio" in text
        assert "Total | 3000" in text

    def test_small_image_upscaled_before_ocr(self, tmp_path, monkeypatch):
        """Phone-photo-res images get a 2x upscale so small text reads better."""
        seen = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen["image_url"] = json["document"]["image_url"]
            return _Response(200, {"pages": [{"markdown": MARKDOWN}]})

        monkeypatch.setattr(httpx, "post", fake_post)
        ocr_image_convert(make_image(tmp_path, "invoice.png"), api_key="k")

        import base64
        from io import BytesIO

        from PIL import Image

        raw = base64.b64decode(seen["image_url"].split(",", 1)[1])
        with Image.open(BytesIO(raw)) as img:
            assert img.size == (640, 480), img.size  # 320x240 upscaled 2x

    def test_raises_on_http_error(self, tmp_path, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            return _Response(500, {"message": "boom"})

        monkeypatch.setattr(httpx, "post", fake_post)
        with pytest.raises(Exception):
            ocr_image_convert(make_image(tmp_path), api_key="k")

    def test_raises_when_no_pages(self, tmp_path, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            return _Response(200, {"pages": []})

        monkeypatch.setattr(httpx, "post", fake_post)
        with pytest.raises(RuntimeError, match="no pages"):
            ocr_image_convert(make_image(tmp_path), api_key="k")


class TestMarkitdownFallback:
    def test_empty_image_text_still_converts(self, tmp_path, monkeypatch):
        """An image tesseract can't read shouldn't hard-fail conversion."""
        def fake_post(url, headers=None, json=None, timeout=None):
            raise RuntimeError("OCR down")

        monkeypatch.setattr(httpx, "post", fake_post)
        with pytest.raises(RuntimeError, match="OCR down"):
            ocr_image_convert(make_image(tmp_path), api_key="k")

    def test_image_exts_covered(self):
        assert {".png", ".jpg", ".jpeg", ".webp", ".bmp"} <= IMAGE_EXTS


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload