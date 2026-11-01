"""Semaforo HRV sulla media mobile.

Il punto: una mattina bassa isolata non accende nulla, una settimana bassa
sì. Le serie sono quelle reali di Francesco (ottobre 2026), dove la soglia
fissa a 39 dava rosso una mattina su tre.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from insights_engine import hrv_rolling_zone  # noqa: E402

RULE = {"short_days": 7, "short_min": 5, "baseline_days": 60, "baseline_min": 30,
        "k_zona2": 0.5, "k_recovery": 1.0}


def _series(end: str, values: list[float]) -> dict[str, float]:
    """values in ordine cronologico, l'ultimo cade su `end`."""
    e = date.fromisoformat(end)
    n = len(values)
    return {(e - timedelta(days=n - 1 - i)).isoformat(): v for i, v in enumerate(values)}


# Fascia stabile attorno a 41 (±6), come l'estate di Francesco.
BASE = [41, 32, 50, 35, 47, 40, 33, 49, 43, 38] * 6


def test_mattina_bassa_isolata_resta_verde():
    s = _series("2026-11-01", BASE + [41, 44, 39, 42, 40, 43, 33])
    assert hrv_rolling_zone(s, "2026-11-01", RULE)["zone"] == "verde"


def test_ottobre_reale_settimana_bassa_e_zona2():
    # 26/10 → 1/11 reali: nessuno sotto 29, ma tutti sotto la fascia.
    s = _series("2026-11-01", BASE + [35.8, 34.3, 36.6, 28.9, 40.7, 36.05, 37.4])
    z = hrv_rolling_zone(s, "2026-11-01", RULE)
    assert z["zone"] == "zona2"
    assert not z["today_low"]


def test_settimana_crollata_e_recupero_con_mattina_bassa():
    s = _series("2026-11-01", BASE + [33, 32, 34, 31, 33, 32, 30])
    z = hrv_rolling_zone(s, "2026-11-01", RULE)
    assert z["zone"] == "recupero"
    assert z["today_low"]


def test_baseline_esclude_la_settimana_corrente():
    # Se la settimana bassa entrasse nella baseline, la fascia scenderebbe con lei.
    s = _series("2026-11-01", BASE + [30] * 7)
    z = hrv_rolling_zone(s, "2026-11-01", RULE)
    assert z["baseline_mean"] == 40.8


def test_storico_insufficiente_non_giudica():
    s = _series("2026-11-01", [40] * 20)
    assert hrv_rolling_zone(s, "2026-11-01", RULE) is None


def test_dispersione_zero_non_scambia_un_decimo_per_recupero():
    s = _series("2026-11-01", [40.0] * 60 + [39.9] * 7)
    assert hrv_rolling_zone(s, "2026-11-01", {**RULE, "sd_floor": 2.0})["zone"] == "verde"


def test_soglia_esposta_nel_messaggio_e_quella_vera():
    s = _series("2026-11-01", BASE + [35.8, 34.3, 36.6, 28.9, 40.7, 36.05, 37.4])
    z = hrv_rolling_zone(s, "2026-11-01", RULE)
    assert z["threshold"] == round(z["baseline_mean"] - 0.5 * z["baseline_sd"], 1)
