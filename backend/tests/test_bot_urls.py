import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TELEGRAM_DIR = ROOT / "telegram"
if str(TELEGRAM_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_DIR))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot


def _origin(monkeypatch, origin):
    monkeypatch.setattr(bot, "FRONTEND_ORIGIN", origin)


class TestButtonSafeOrigin:
    def test_rejects_localhost_http(self, monkeypatch):
        _origin(monkeypatch, "http://localhost:3000")
        assert not bot._button_safe_origin()

    def test_rejects_https_localhost(self, monkeypatch):
        _origin(monkeypatch, "https://localhost:3000")
        assert not bot._button_safe_origin()

    def test_rejects_http_public(self, monkeypatch):
        _origin(monkeypatch, "http://demo.example.com")
        assert not bot._button_safe_origin()

    def test_accepts_https_public(self, monkeypatch):
        _origin(monkeypatch, "https://demo.example.com")
        assert bot._button_safe_origin()

    def test_link_line_uses_origin(self, monkeypatch):
        _origin(monkeypatch, "https://demo.example.com")
        assert (bot._dashboard_link_line("/ledger?month=2026-08")
                == "Dashboard: https://demo.example.com/ledger?month=2026-08")
