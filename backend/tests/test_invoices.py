import types
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.routes.invoices import _safe_filename, _save_upload


class TestSafeFilename:
    def test_plain_kept(self):
        assert _safe_filename("invoice.pdf") == "invoice.pdf"

    def test_strips_unix_path_components(self):
        assert _safe_filename("../../etc/cron.d/evil.pdf") == "evil.pdf"

    def test_strips_windows_path_components(self):
        assert _safe_filename(r"..\..\evil.txt") == "evil.txt"
        assert _safe_filename(r"C:\Windows\evil.pdf") == "evil.pdf"

    def test_fallback_when_empty(self):
        assert _safe_filename(None) == "upload.bin"
        assert _safe_filename("") == "upload.bin"
        assert _safe_filename("../") == "upload.bin"
        assert _safe_filename("..") == "upload.bin"
        assert _safe_filename(".") == "upload.bin"


class TestSaveUpload:
    def test_traversal_filename_written_inside_upload_dir(self, tmp_path, monkeypatch):
        settings = types.SimpleNamespace(upload_dir=str(tmp_path))
        monkeypatch.setattr("app.routes.invoices.get_settings", lambda: settings)

        upload = UploadFile(BytesIO(b"hello"), filename="../../escape.pdf")
        dest = _save_upload(upload)

        assert dest.resolve().is_relative_to(tmp_path.resolve())
        assert dest.name == "escape.pdf"
        assert dest.read_bytes() == b"hello"

    def test_normal_filename_written_to_upload_dir(self, tmp_path, monkeypatch):
        settings = types.SimpleNamespace(upload_dir=str(tmp_path))
        monkeypatch.setattr("app.routes.invoices.get_settings", lambda: settings)

        upload = UploadFile(BytesIO(b"data"), filename="bill_2025.pdf")
        dest = _save_upload(upload)

        assert dest == Path(tmp_path) / "bill_2025.pdf"
        assert dest.read_bytes() == b"data"