"""_fetch_minutes: la cache al minuto (usata anche dal cancello di Hṛdaya per l'alzata)."""
import json
import sys
import types

import meditation_detect as md


def test_cache_completa_non_chiama_la_rete(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "MINUTE", tmp_path)
    (tmp_path / "2026-11-04.json").write_text(json.dumps(
        {"date": "2026-11-04", "complete": True, "hr": {"06:50": 70.0}, "steps": {"06:51": 30}}))
    monkeypatch.setitem(sys.modules, "health_sync", None)   # import → errore se toccato
    assert md._fetch_minutes("2026-11-04")["steps"] == {"06:51": 30}


def test_rete_assente_torna_la_cache_parziale(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "MINUTE", tmp_path)
    (tmp_path / "2026-11-04.json").write_text(json.dumps(
        {"date": "2026-11-04", "complete": False, "hr": {"06:50": 70.0}, "steps": {}}))
    broken = types.ModuleType("health_sync")

    class Boom:
        def __init__(self, *_a):
            raise OSError("offline")
    broken.HealthClient = Boom
    monkeypatch.setitem(sys.modules, "health_sync", broken)
    assert md._fetch_minutes("2026-11-04")["hr"] == {"06:50": 70.0}


def test_niente_cache_niente_rete_none(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "MINUTE", tmp_path)
    monkeypatch.setitem(sys.modules, "health_sync", None)
    assert md._fetch_minutes("2026-11-04") is None
