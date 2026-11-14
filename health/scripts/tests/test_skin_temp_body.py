"""Temperatura cutanea notturna, bilancia (peso e massa grassa) e segnale skin_temp_rise."""
import unittest
from unittest import mock

import insights_engine as ie
from health_extract import extract_body, extract_sleep_temperature

TEMP_POINT = {"dataSource": {"platform": "FITBIT"}, "dailySleepTemperatureDerivations": {
    "date": {"year": 2026, "month": 11, "day": 14}, "nightlyTemperatureCelsius": 32.95,
    "baselineTemperatureCelsius": "32.9", "relativeNightlyStddev30dCelsius": 0.57}}


class SleepTemperatureTest(unittest.TestCase):
    def test_scostamento_dalla_baseline_anche_con_stringhe(self):
        self.assertEqual(extract_sleep_temperature([TEMP_POINT]),
                         {"nightly_c": 32.95, "baseline_c": 32.9, "delta_c": 0.05, "sd30_c": 0.57})

    def test_senza_baseline_solo_il_valore(self):
        p = {"dailySleepTemperatureDerivations": {"nightlyTemperatureCelsius": 33.1}}
        self.assertEqual(extract_sleep_temperature([p]), {"nightly_c": 33.1})

    def test_vuoto(self):
        self.assertIsNone(extract_sleep_temperature([]))


class BodyTest(unittest.TestCase):
    def test_ultima_misura_del_giorno(self):
        w = [{"weight": {"weightGrams": 62400, "sampleTime": {"physicalTime": "2026-11-14T07:10:00Z"}},
              "dataSource": {"device": {"displayName": "Renpho"}}},
             {"weight": {"weightGrams": "62100", "sampleTime": {"physicalTime": "2026-11-14T19:00:00Z"}},
              "dataSource": {"device": {"displayName": "Renpho"}}}]
        f = [{"bodyFat": {"percentage": 27.36, "sampleTime": {"physicalTime": "2026-11-14T07:10:00Z"}}}]
        self.assertEqual(extract_body(w, f), {"weight_kg": 62.1, "body_source": "Renpho", "body_fat_pct": 27.4})

    def test_niente_bilancia_niente_chiavi(self):
        self.assertEqual(extract_body([], []), {})


def _days(*deltas):
    return [{"date": f"2026-11-{15 - len(deltas) + i:02d}", "skin_temp": {"delta_c": d}}
            for i, d in enumerate(deltas)]


class SkinTempRiseTest(unittest.TestCase):
    def run_rule(self, days, rules=None):
        with mock.patch.object(ie, "fitbit_days_back", lambda n, end=None: days[-n:]):
            return ie.detect_skin_temp({"rules": rules or {}}, "2026-11-14")

    def test_due_notti_sopra_soglia(self):
        ev = self.run_rule(_days(0.8, 1.1))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["rule"], "skin_temp_rise")
        self.assertEqual(ev[0]["deliver"], "morning")
        self.assertIn("+0.8 → +1.1", ev[0]["message"])

    def test_una_notte_sola_o_dato_mancante_no(self):
        self.assertEqual(self.run_rule(_days(0.2, 1.3)), [])
        self.assertEqual(self.run_rule([{"date": "2026-11-13"}, {"date": "2026-11-14", "skin_temp": {"delta_c": 1}}]), [])
        self.assertEqual(self.run_rule(_days(1.0)), [])          # manca una notte

    def test_episodio_segnalato_una_volta(self):
        self.assertEqual(len(self.run_rule(_days(0.1, 0.8, 1.1))), 1)
        self.assertEqual(self.run_rule(_days(0.9, 0.8, 1.1)), [])   # terza notte calda: già detto ieri

    def test_soglia_e_spegnimento_da_config(self):
        self.assertEqual(self.run_rule(_days(0.8, 0.9), {"skin_temp_rise": {"delta_c": 1.0}}), [])
        self.assertEqual(self.run_rule(_days(2, 2), {"skin_temp_rise": {"enabled": False}}), [])


if __name__ == "__main__":
    unittest.main()
