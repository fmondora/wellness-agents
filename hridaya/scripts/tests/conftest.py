"""Test del plugin hridaya: ogni test ha il suo repo dati finto; nessuna rete."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Repo dati minimo: profilo, .env col token finto, ritmo con ora di letto 22:15."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "profile.json").write_text("{}")
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=123:T\nALLOWED_CHAT_IDS=42\n"
                                   "WORKOUT_PLAYER_URL=https://x.pages.dev/\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "insights.json").write_text(json.dumps(
        {"circadian": {"target_wake": "06:00", "cycle_min": 90, "onset_latency_min": 15,
                       "cycles_options": [5, 4]}}))
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("HRIDAYA_TRANSPORT_LOG", raising=False)
    return tmp_path


class FakeCall:
    """call(token, method, **params) finta: registra, risponde ok."""

    def __init__(self, fail: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail or {}

    def __call__(self, token, method, **params):
        self.calls.append((method, params))
        if method in self.fail:
            raise self.fail[method]
        if method == "getMe":
            return {"ok": True, "result": {"username": "hridaya_bot", "first_name": "Hridaya"}}
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": ""}}
        return {"ok": True, "result": {"message_id": len(self.calls)}}

    def texts(self, method="sendMessage"):
        return [p.get("text") for m, p in self.calls if m == method]


@pytest.fixture
def fake_call():
    return FakeCall()
