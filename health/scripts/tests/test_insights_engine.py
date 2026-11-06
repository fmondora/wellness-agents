import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from insights_engine import (detect_intense_session, detect_long_walk,
                                     load_config, _in_quiet_hours, _sequences)
from health_metrics import normalize_hrv, robust_baseline, robust_zscore

TZ = ZoneInfo("Europe/Rome")
CFG = load_config()


def _walk_day(start_h=9, buckets=10, steps=900):
    """Giornata sintetica con camminata di `buckets` bucket da 15 min."""
    out = []
    for i in range(buckets):
        total_min = start_h * 60 + i * 15
        out.append({"time": f"{total_min // 60:02d}:{total_min % 60:02d}", "steps": steps})
    return {"steps_intraday": out}


class LongWalkTest(unittest.TestCase):
    def test_camminata_2h_rilevata(self):
        day = _walk_day(buckets=8)  # 2h, 7200 passi
        events = detect_long_walk(day, CFG, "2026-07-12", now=None)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["duration_min"], 120)
        self.assertEqual(events[0]["data"]["steps"], 7200)

    def test_camminata_breve_non_rilevata(self):
        day = _walk_day(buckets=4)  # 1h < 90 min
        self.assertEqual(detect_long_walk(day, CFG, "2026-07-12", None), [])

    def test_gap_2_bucket_tollerato(self):
        day = _walk_day(buckets=8, steps=1100)
        # svuota 2 bucket in mezzo (bar/semaforo): la sequenza deve reggere
        day["steps_intraday"][3]["steps"] = 100
        day["steps_intraday"][4]["steps"] = 50
        events = detect_long_walk(day, CFG, "2026-07-12", None)
        self.assertEqual(len(events), 1)

    def test_gap_3_bucket_spezza(self):
        day = _walk_day(buckets=12)
        for i in (4, 5, 6):
            day["steps_intraday"][i]["steps"] = 0
        day["steps_intraday"] = [b for b in day["steps_intraday"] if b["steps"] > 0]
        events = detect_long_walk(day, CFG, "2026-07-12", None)
        # due tronconi da 60/75 min: nessuno qualifica
        self.assertEqual(events, [])

    def test_non_fire_se_in_corso(self):
        # camminata che finisce alle 11:00, ora sono le 11:10 → non ancora
        day = _walk_day(start_h=9, buckets=8)
        now = datetime(2026, 7, 12, 11, 10, tzinfo=TZ)
        self.assertEqual(detect_long_walk(day, CFG, "2026-07-12", now), [])
        # alle 11:35 (fine + 2 bucket + 5) → fire
        now = datetime(2026, 7, 12, 11, 35, tzinfo=TZ)
        self.assertEqual(len(detect_long_walk(day, CFG, "2026-07-12", now)), 1)

    def test_giorno_sedentario_nessun_evento(self):
        day = {"steps_intraday": [{"time": "10:00", "steps": 300},
                                  {"time": "15:00", "steps": 500}]}
        self.assertEqual(detect_long_walk(day, CFG, "2026-07-21", None), [])


def _crossfit_day():
    """CrossFit-like: 3 bucket HR alta 9:00-9:45, pochi passi."""
    hr = [{"time": "08:45", "avg": 80.0},
          {"time": "09:00", "avg": 118.0, "max": 145.0},
          {"time": "09:15", "avg": 131.0, "max": 152.0},
          {"time": "09:30", "avg": 122.0, "max": 140.0},
          {"time": "09:45", "avg": 92.0}]
    steps = [{"time": "09:00", "steps": 400}, {"time": "09:15", "steps": 350}]
    azm = [{"time": "09:10", "zone": "CARDIO", "minutes": 1},
           {"time": "09:20", "zone": "PEAK", "minutes": 1}]
    return {"heart_rate_15min": hr, "steps_intraday": steps, "azm": azm}


class IntenseSessionTest(unittest.TestCase):
    def test_crossfit_rilevato(self):
        events = detect_intense_session(_crossfit_day(), CFG, "2026-07-13", None)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["data"]["start"], "09:00")
        self.assertEqual(e["data"]["duration_min"], 45)
        self.assertEqual(e["data"]["azm_intense_min"], 2)

    def test_camminata_veloce_esclusa(self):
        # HR alta ma TANTI passi → non è sessione intensa "ferma"
        day = _crossfit_day()
        day["steps_intraday"] = [{"time": "09:00", "steps": 1500},
                                 {"time": "09:15", "steps": 1400}]
        self.assertEqual(detect_intense_session(day, CFG, "2026-07-13", None), [])

    def test_singolo_bucket_non_basta(self):
        day = {"heart_rate_15min": [{"time": "09:00", "avg": 130.0, "max": 150.0}],
               "steps_intraday": []}
        self.assertEqual(detect_intense_session(day, CFG, "2026-07-13", None), [])


class SequencesTest(unittest.TestCase):
    def test_sequenza_unica(self):
        buckets = [{"time": "09:00", "steps": 900}, {"time": "09:15", "steps": 900}]
        self.assertEqual(len(_sequences(buckets, 800, 2)), 1)

    def test_sequenze_separate(self):
        buckets = [{"time": "09:00", "steps": 900}, {"time": "12:00", "steps": 900}]
        self.assertEqual(len(_sequences(buckets, 800, 2)), 2)


class QuietHoursTest(unittest.TestCase):
    # config esplicita: la logica va testata a prescindere dagli orari scelti
    CFG_CROSS = {"quiet_hours": {"start": "23:00", "end": "04:30"}}

    def test_notte_fonda_e_quiet(self):
        self.assertTrue(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 23, 30, tzinfo=TZ)))
        self.assertTrue(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 3, 0, tzinfo=TZ)))

    def test_fuori_dalla_fascia_non_quiet(self):
        # 22:30 e 05:00 sono ATTIVI con la fascia stretta 23:00-04:30
        self.assertFalse(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 22, 30, tzinfo=TZ)))
        self.assertFalse(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 5, 0, tzinfo=TZ)))
        self.assertFalse(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 12, 0, tzinfo=TZ)))

    def test_confine_esatto(self):
        # start incluso, end escluso
        self.assertTrue(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 23, 0, tzinfo=TZ)))
        self.assertFalse(_in_quiet_hours(self.CFG_CROSS, datetime(2026, 7, 26, 4, 30, tzinfo=TZ)))


class NormalizeHrvTest(unittest.TestCase):
    def test_scala_hrv4training(self):
        self.assertEqual(normalize_hrv(7.2), ("hrv4training", 7.2))

    def test_scala_rmssd(self):
        self.assertEqual(normalize_hrv(50.4), ("rmssd_ms", 50.4))

    def test_valori_invalidi(self):
        self.assertIsNone(normalize_hrv(None))
        self.assertIsNone(normalize_hrv("x"))
        self.assertIsNone(normalize_hrv(0))


class CircadianTest(unittest.TestCase):
    def test_solar_sondrio_luglio(self):
        from datetime import date
        from trends import solar_times
        s = solar_times(date(2026, 7, 26))
        # Nord Italia (fixture: Milano) a fine luglio: alba ~5:45-6:10, tramonto ~20:45-21:10 CEST
        self.assertTrue("05:4" in s["sunrise"] or "05:5" in s["sunrise"] or "06:0" in s["sunrise"])
        self.assertTrue(s["sunset"].startswith("20:") or s["sunset"].startswith("21:0"))
        self.assertGreater(s["photoperiod_h"], 14.5)

    def test_solar_inverno_piu_corto(self):
        from datetime import date
        from trends import solar_times
        inverno = solar_times(date(2026, 12, 21))
        self.assertLess(inverno["photoperiod_h"], 9.0)

    def test_since_noon_niente_wrap(self):
        from trends import _since_noon, _fmt_clock
        # 23:00 e 00:30 devono essere vicini, non a 22.5h di distanza
        a, b = _since_noon(23 * 60), _since_noon(30)
        self.assertEqual(b - a, 90)
        self.assertEqual(_fmt_clock(a + 720), "23:00")


class RobustStatsTest(unittest.TestCase):
    def test_baseline_e_zscore(self):
        base = robust_baseline([400, 420, 440, 410, 430])
        self.assertEqual(base["median"], 420)
        z = robust_zscore(300, base)
        self.assertLess(z, -1.5)

    def test_baseline_pochi_dati(self):
        self.assertIsNone(robust_baseline([420, 430]))


if __name__ == "__main__":
    unittest.main()


class SleepAnalysisTest(unittest.TestCase):
    # la notte reale del repo dati non è nel plugin: qui solo il caso assente
    def test_notte_assente(self):
        from sleep_analysis import analyze
        self.assertIsNone(analyze("1999-01-01"))
