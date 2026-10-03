"""Firma della veglia abitata — il risveglio notturno che diventa pratica.

Il punto delicato non è riconoscere che qualcuno si è alzato: è distinguere
chi si siede sul cuscino da chi prende il telefono. Entrambi producono passi
isolati e FC sopra il pavimento notturno. A separarli è la coda: dopo la
pratica il sistema scende SOTTO il livello pre-risveglio, dopo il rimuginio
resta sopra. Questi test difendono quella distinzione.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health_metrics import DEFAULT_NIGHT_PRACTICE, night_practice_windows  # noqa: E402

SESSION = {"start": "22:43", "end": "06:41", "minutes_asleep": 371}


def _day(hr_rows, step_rows=None):
    return {
        "heart_rate_15min": [{"time": t, "avg": a, "max": a + 20, "min": a - 5}
                             for t, a in hr_rows],
        "steps_intraday": [{"time": t, "steps": s} for t, s in (step_rows or [])],
    }


# Notte reale del 2026-10-03: Francesco si sveglia verso le 4, invece di
# guardare il telefono si siede sul cuscino e medita.
NOTTE_3_OTTOBRE = _day(
    [("03:00", 52.3), ("03:15", 49.7), ("03:30", 51.1), ("03:45", 49.5),
     ("04:00", 50.1), ("04:15", 57.2), ("04:30", 58.6), ("04:45", 58.7),
     ("05:00", 55.3), ("05:15", 51.4), ("05:30", 49.8), ("05:45", 48.1),
     ("06:00", 47.7), ("06:15", 45.5), ("06:30", 50.4)],
    [("03:00", 4), ("04:15", 22)],
)


def test_riconosce_la_pratica_del_3_ottobre():
    w = night_practice_windows(NOTTE_3_OTTOBRE, SESSION, DEFAULT_NIGHT_PRACTICE)
    assert len(w) == 1
    assert w[0]["start"] == "04:15"
    assert w[0]["minutes"] >= 45
    assert w[0]["ratified"] is True


def test_senza_ratifica_non_e_pratica():
    """Stessa alzata, stesso plateau — ma la FC non torna mai sotto il
    livello pre-risveglio. È il profilo del telefono, non del cuscino."""
    rimuginio = _day(
        [("03:45", 49.5), ("04:00", 50.1), ("04:15", 57.2), ("04:30", 58.6),
         ("04:45", 58.7), ("05:00", 55.3), ("05:15", 52.0), ("05:30", 51.8),
         ("05:45", 52.4), ("06:00", 51.0), ("06:15", 50.9)],
        [("04:15", 22)],
    )
    w = night_practice_windows(rimuginio, SESSION, DEFAULT_NIGHT_PRACTICE)
    assert w == []


def test_plateau_da_attivita_non_e_pratica():
    """FC da postura seduta, non da movimento: sopra il tetto non si guarda."""
    attivita = _day(
        [("03:45", 49.5), ("04:00", 50.1), ("04:15", 92.0), ("04:30", 95.0),
         ("04:45", 94.0), ("05:00", 60.0), ("05:15", 48.0)],
        [("04:15", 40)],
    )
    assert night_practice_windows(attivita, SESSION, DEFAULT_NIGHT_PRACTICE) == []


def test_risveglio_breve_non_e_pratica():
    """Un bagno alle 4 non è una pratica: un solo bucket sopra soglia."""
    bagno = _day(
        [("03:45", 49.5), ("04:00", 50.1), ("04:15", 57.0), ("04:30", 49.0),
         ("04:45", 47.5), ("05:00", 47.0)],
        [("04:15", 30)],
    )
    assert night_practice_windows(bagno, SESSION, DEFAULT_NIGHT_PRACTICE) == []


def test_senza_alzata_non_e_pratica():
    """Plateau e ratifica ci sono, ma nessun passo: è un risveglio a letto."""
    a_letto = _day(
        [("03:45", 49.5), ("04:00", 50.1), ("04:15", 57.2), ("04:30", 58.6),
         ("04:45", 58.7), ("05:00", 55.3), ("05:15", 48.0)],
        [],
    )
    assert night_practice_windows(a_letto, SESSION, DEFAULT_NIGHT_PRACTICE) == []


def test_camminata_notturna_non_e_pratica():
    """Troppi passi: si è mosso, non si è seduto."""
    camminata = _day(
        [("03:45", 49.5), ("04:00", 50.1), ("04:15", 57.2), ("04:30", 58.6),
         ("04:45", 58.7), ("05:00", 55.3), ("05:15", 48.0)],
        [("04:15", 350), ("04:30", 280)],
    )
    assert night_practice_windows(camminata, SESSION, DEFAULT_NIGHT_PRACTICE) == []


def test_fuori_dalla_sessione_di_sonno_non_si_guarda():
    """Le 07:30 sono mattina, non veglia abitata dentro la notte."""
    mattina = _day(
        [("07:00", 49.5), ("07:15", 50.1), ("07:30", 57.2), ("07:45", 58.6),
         ("08:00", 58.7), ("08:15", 55.3), ("08:30", 48.0)],
        [("07:30", 22)],
    )
    assert night_practice_windows(mattina, SESSION, DEFAULT_NIGHT_PRACTICE) == []


def test_regola_disabilitata():
    rule = dict(DEFAULT_NIGHT_PRACTICE, enabled=False)
    assert night_practice_windows(NOTTE_3_OTTOBRE, SESSION, rule) == []


def test_senza_dati_intraday_nessuna_finestra():
    assert night_practice_windows({}, SESSION, DEFAULT_NIGHT_PRACTICE) == []
    assert night_practice_windows(NOTTE_3_OTTOBRE, None, DEFAULT_NIGHT_PRACTICE) == []
