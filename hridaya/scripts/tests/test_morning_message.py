"""Fallback deterministici: notte, eventi del mattino, scadenze 48 h, sera con prelievo."""
import json

import morning_message as mm


def _write(data, rel, obj):
    p = data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)


def test_scadenze_solo_48h_e_scadute(data):
    _write(data, "data/scadenze.json", {"items": [
        {"id": "a", "title": "Prenotare visita", "due": "2026-11-08"},
        {"id": "b", "title": "Lontana", "due": "2026-11-30"},
        {"id": "c", "title": "Scaduta", "due": "2026-11-01"},
        {"id": "d", "title": "Fatta", "due": "2026-11-07", "done": True}]})
    got = [it["id"] for it in mm.deadlines("2026-11-06")]
    assert got == ["c", "a"]
    lines = mm.format_deadlines(mm.deadlines("2026-11-06"))
    assert "SCADUTA" in lines[1] and "tra 2 gg" in lines[2]


def test_sera_ora_di_letto_e_prelievo_domani(data):
    _write(data, "data/scadenze.json", {"items": [
        {"id": "prelievo-tsh", "title": "Prelievo ore 8", "due": "2026-11-07"}]})
    txt = mm.evening_text("2026-11-06")
    assert "22:15" in txt and "automatico" in txt
    assert "Prelievo ore 8" in txt and "digiuno" in txt


def test_sera_senza_prelievo(data):
    txt = mm.evening_text("2026-11-06")
    assert "🩸" not in txt and "22:15" in txt


def test_mattino_notte_eventi_scadenze(data):
    night = {"sleep": [{"start": "22:49", "end": "06:45", "minutes_asleep": 420,
                        "stages": [{"type": "DEEP", "minutes": 60}, {"type": "REM", "minutes": 90},
                                   {"type": "AWAKE", "minutes": 30}]}],
             "hrv_rmssd": 44.0, "resting_hr": 52}
    _write(data, "data/fitbit/2026-11-07.json", night)
    _write(data, "data/insights/events/2026-11-07.jsonl",
           json.dumps({"id": "e1", "deliver": "morning", "delivered": False, "message": "Notte corta?"}) + "\n")
    _write(data, "data/scadenze.json", {"items": [{"id": "x", "title": "Ritira referto", "due": "2026-11-07"}]})
    txt = mm.wake_text("2026-11-07")
    assert "22:49–06:45" in txt and "7h00" in txt and "DEEP 60m" in txt and "HRV 44" in txt
    assert "Notte corta?" in txt and "Ritira referto" in txt
    ev = json.loads((data / "data/insights/events/2026-11-07.jsonl").read_text())
    assert ev["delivered"] is True
    assert "Notte corta?" not in mm.wake_text("2026-11-07")     # consegnato una volta


def test_mattino_senza_dati(data):
    assert "non sono ancora arrivati" in mm.wake_text("2026-11-07", mark=False)
