"""Tre orizzonti: settimana contro fascia, trimestre contro trimestre, anno.

Il punto delicato è la copertura: con pochi mesi di storico l'anno esiste
ma è parziale, e il trimestre precedente può mancare. Mai inventare un
confronto che i dati non reggono.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trends import horizons  # noqa: E402

END = "2026-11-01"


def _points(values: list[float], end: str = END) -> list[tuple[str, float]]:
    e = date.fromisoformat(end)
    n = len(values)
    return [((e - timedelta(days=n - 1 - i)).isoformat(), v) for i, v in enumerate(values)]


WAVE = [41, 32, 50, 35, 47, 40, 33, 49, 43, 38]


def test_settimana_bassa_sotto_la_fascia():
    h = horizons(_points(WAVE * 6 + [33, 32, 34, 31, 33, 32, 30]), END)
    assert h["settimana"]["position"] == "sotto"
    assert h["settimana"]["band_mean"] == 40.8


def test_trimestre_confronta_col_trimestre_prima():
    h = horizons(_points([44.0] * 90 + [38.0] * 90), END)
    t = h["trimestre"]
    assert (t["prev_median"], t["median"], t["delta"]) == (44.0, 38.0, -6.0)


def test_storico_corto_niente_trimestre_prima_e_anno_parziale():
    h = horizons(_points(WAVE * 11), END)  # 110 giorni, come Fitbit da luglio
    assert h["trimestre"]["delta"] is None
    assert h["anno"]["n"] == 110
    assert h["anno"]["coverage"] == 0.3


def test_anno_vede_la_discesa():
    h = horizons(_points([50 - i * 0.03 for i in range(365)]), END)
    assert h["anno"]["trend"] == "↓"
    assert h["anno"]["slope_per_month"] == -0.9


def test_pochi_dati_nessun_orizzonte():
    assert horizons(_points([40.0] * 10), END) == {}


def test_fascia_piatta_il_pavimento_separa_rumore_da_segnale():
    piatta = [55.0] * 60
    poco = horizons(_points(piatta + [55, 55, 56, 55, 56, 55, 56]), END, sd_floor=1.0)
    tanto = horizons(_points(piatta + [57.0] * 7), END, sd_floor=1.0)
    assert poco["settimana"]["position"] == "dentro"
    assert tanto["settimana"]["position"] == "sopra"
