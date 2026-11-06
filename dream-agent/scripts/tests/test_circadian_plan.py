"""Ora di letto a fine ciclo e sveglia ciclo-allineata."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def cp(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "data" / "fitbit").mkdir(parents=True)
    (tmp_path / "config" / "insights.json").write_text(json.dumps({
        "circadian": {"target_wake": "06:00", "cycle_min": 90, "onset_latency_min": 15, "cycles_options": [5, 4]},
        "therapy_nudge": {"enabled": True, "items": [{"text": "💊 promemoria", "days": ["lun", "gio"]}]}}))
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import importlib
    import circadian_plan
    mod = importlib.reload(circadian_plan)
    monkeypatch.setattr(mod, "load_fitbit_day", lambda d: json.loads(
        (tmp_path / "data" / "fitbit" / f"{d}.json").read_text()) if (tmp_path / "data" / "fitbit" / f"{d}.json").exists() else None)
    return mod, tmp_path


def test_ora_di_letto_a_fine_ciclo(cp):
    mod, _ = cp
    ev = mod.evening_plan()
    assert ev["recommended_bedtime"] == "22:15"           # 06:00 − 5×90′ − 15′
    assert [o["bedtime"] for o in ev["options"]] == ["22:15", "23:45"]


def test_promemoria_solo_nei_giorni_nominati(cp):
    mod, _ = cp
    assert mod.therapy_reminders(datetime(2026, 11, 9)) == ["💊 promemoria"]     # lunedì
    assert mod.therapy_reminders(datetime(2026, 11, 10)) == []


def test_sveglia_dal_sonno_reale(cp):
    mod, root = cp
    (root / "data" / "fitbit" / "2026-11-07.json").write_text(json.dumps(
        {"sleep": [{"start": "22:30", "end": "06:10", "minutes_asleep": 400}]}))
    m = mod.morning_plan("2026-11-07")
    assert m["onset_source"] == "reale" and m["cycle_aligned"]
    assert m["wake"] == "06:15"                            # addormentato 22:45 + 5×90′, dentro 05:20–06:20


def test_senza_dati_usa_il_previsto(cp):
    mod, _ = cp
    assert mod.morning_plan("2026-11-08")["onset_source"] == "previsto"


def test_nessun_fine_ciclo_nella_finestra_resta_il_target(cp):
    mod, root = cp
    (root / "data" / "fitbit" / "2026-11-09.json").write_text(json.dumps(
        {"sleep": [{"start": "22:45", "end": "06:10", "minutes_asleep": 400}]}))
    m = mod.morning_plan("2026-11-09")
    assert m["wake"] == "06:00" and not m["cycle_aligned"]   # 05:00 e 06:30 fuori finestra
