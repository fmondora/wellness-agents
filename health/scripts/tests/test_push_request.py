"""Il detector non scrive più in outbox: chiede il push al cancello di Hṛdaya."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import insights_engine as ie
from push_request import request_push

TZ = ZoneInfo("Europe/Rome")


def _rows(base):
    f = base / "data" / "telegram" / "push.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_request_push_idempotente(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    request_push("ciao", source="test", push_id="x1")
    request_push("ciao", source="test", push_id="x1")
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending" and rows[0]["priority"] == "normal"


def test_evento_immediato_di_notte_va_al_cancello(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    monkeypatch.setattr(ie, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(ie, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(ie, "load_env", lambda: {"ALLOWED_CHAT_IDS": "42"})
    cfg = {"quiet_hours": {"start": "23:00", "end": "04:30"}, "daily_budget": 3}
    ev = {"id": "long_walk-2026-07-12-1500", "date": "2026-07-12", "rule": "long_walk",
          "deliver": "immediate", "message": "🚶 camminata", "question": "Com'era?",
          "log_target": "movement.walk_note"}
    now = datetime(2026, 7, 12, 23, 30, tzinfo=TZ)   # dentro le vecchie quiet hours
    state: dict = {}
    out = ie.process_events([ev], cfg, state, now)
    assert out[0]["deliver"] == "immediate" and out[0]["requalified"] is None
    rows = _rows(tmp_path)
    assert [r["id"] for r in rows] == ["insight-long_walk-2026-07-12-1500"]
    assert rows[0]["kind"] == "detector"
    assert not (tmp_path / "data" / "telegram" / "outbox.jsonl").exists()
    assert state["open_questions"][0]["event_id"] == ev["id"]
