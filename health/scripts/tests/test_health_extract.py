import unittest

from health_extract import (extract_azm, extract_daily_value,
                                    extract_hr_hourly, extract_hr_intraday,
                                    extract_hr_stats, extract_sleep,
                                    extract_steps, extract_steps_intraday,
                                    first_number)

# Forme reali osservate in data/fitbit/probe.json (Task 2) — sostituiscono
# i fixture ipotetici del brief originale.

SLEEP_POINT = {
    "name": "users/123/dataTypes/sleep/dataPoints/456",
    "dataSource": {"recordingMethod": "DERIVED", "device": {}, "platform": "FITBIT"},
    "sleep": {
        "interval": {"startTime": "2026-07-08T21:30:00Z",
                     "endTime": "2026-07-09T05:10:00Z"},
        "type": "STAGES",
        "stages": [
            {"startTime": "2026-07-08T21:30:00Z", "endTime": "2026-07-08T21:35:00Z", "type": "AWAKE"},
            {"startTime": "2026-07-08T21:35:00Z", "endTime": "2026-07-09T05:10:00Z", "type": "LIGHT"},
        ],
        "summary": {
            "minutesInSleepPeriod": "460",
            "minutesAsleep": "372",
            "minutesAwake": "5",
            "stagesSummary": [
                {"type": "AWAKE", "minutes": "4", "count": "2"},
                {"type": "LIGHT", "minutes": "252", "count": "12"},
                {"type": "DEEP", "minutes": "49", "count": "6"},
                {"type": "REM", "minutes": "70", "count": "5"},
            ],
        },
    },
}

SLEEP_POINT_NO_SUMMARY = {
    "sleep": {
        "interval": {"startTime": "2026-07-08T21:30:00Z",
                     "endTime": "2026-07-09T05:10:00Z"},
    }
}

DAILY_HRV_POINT = {
    "dataSource": {"recordingMethod": "DERIVED", "device": {}, "platform": "FITBIT"},
    "dailyHeartRateVariability": {
        "date": {"year": 2026, "month": 7, "day": 10},
        "averageHeartRateVariabilityMilliseconds": 44.55,
        "nonRemHeartRateBeatsPerMinute": "50",
        "entropy": 3.153,
        "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 57.8,
    },
}

DAILY_RHR_POINT = {
    "dataSource": {"recordingMethod": "DERIVED", "device": {}, "platform": "FITBIT"},
    "dailyRestingHeartRate": {
        "date": {"year": 2026, "month": 7, "day": 10},
        "beatsPerMinute": "53",
        "dailyRestingHeartRateMetadata": {"calculationMethod": "WITH_SLEEP"},
    },
}

DAILY_SPO2_POINT = {
    "dailyOxygenSaturation": {
        "date": {"year": 2026, "month": 7, "day": 10},
        "averagePercentage": 94.8,
        "lowerBoundPercentage": 94.3,
        "upperBoundPercentage": 95.5,
    }
}

DAILY_RR_POINT = {
    "dailyRespiratoryRate": {
        "date": {"year": 2026, "month": 7, "day": 10},
        "breathsPerMinute": 15.8,
    }
}

HR_ROLLUP = {"rollupDataPoints": [
    # deliberatamente fuori ordine, come osservato nella risposta reale
    {"startTime": "2026-07-08T23:00:00Z", "endTime": "2026-07-09T00:00:00Z",
     "heartRate": {"beatsPerMinuteAvg": 55.0, "beatsPerMinuteMax": 90, "beatsPerMinuteMin": 50}},
    {"startTime": "2026-07-08T22:00:00Z", "endTime": "2026-07-08T23:00:00Z",
     "heartRate": {"beatsPerMinuteAvg": 58.2, "beatsPerMinuteMax": 88, "beatsPerMinuteMin": 52}},
]}

HR_DAILY = {"rollupDataPoints": [
    {"civilStartTime": {"date": {"year": 2026, "month": 7, "day": 8}, "time": {}},
     "civilEndTime": {"date": {"year": 2026, "month": 7, "day": 9}, "time": {}},
     "heartRate": {"beatsPerMinuteAvg": 62.0, "beatsPerMinuteMax": 132.0, "beatsPerMinuteMin": 48.0}},
]}

STEPS_DAILY = {"rollupDataPoints": [
    {"civilStartTime": {"date": {"year": 2026, "month": 7, "day": 8}, "time": {}},
     "civilEndTime": {"date": {"year": 2026, "month": 7, "day": 9}, "time": {}},
     "steps": {"countSum": "8421"}},
]}


class FirstNumberTest(unittest.TestCase):
    def test_trova_numero_annidato(self):
        self.assertEqual(first_number({"a": {"b": [{"c": 42.5}]}}), 42.5)

    def test_ignora_bool_e_stringhe_non_numeriche(self):
        self.assertIsNone(first_number({"a": True, "b": "boh"}))

    def test_accetta_stringhe_numeriche(self):
        # l'API arriva con valori numerici come stringa (es. beatsPerMinute: '53')
        self.assertEqual(first_number({"a": "53"}), 53.0)
        self.assertEqual(first_number("44.55"), 44.55)

    def test_vuoto(self):
        self.assertIsNone(first_number({}))


class ExtractSleepTest(unittest.TestCase):
    def test_sessione_base(self):
        out = extract_sleep([SLEEP_POINT])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["duration_min"], 460)
        # orari in Europe/Rome (UTC+2 a luglio): 21:30Z → 23:30
        self.assertEqual(out[0]["start"], "23:30")
        self.assertEqual(out[0]["end"], "07:10")

    def test_minutes_asleep_e_stages_da_summary(self):
        out = extract_sleep([SLEEP_POINT])
        self.assertEqual(out[0]["minutes_asleep"], 372)
        self.assertEqual(out[0]["stages"], [
            {"type": "AWAKE", "minutes": 4, "count": 2},
            {"type": "LIGHT", "minutes": 252, "count": 12},
            {"type": "DEEP", "minutes": 49, "count": 6},
            {"type": "REM", "minutes": 70, "count": 5},
        ])

    def test_senza_summary_minutes_asleep_e_stages_none(self):
        out = extract_sleep([SLEEP_POINT_NO_SUMMARY])
        self.assertIsNone(out[0]["minutes_asleep"])
        self.assertIsNone(out[0]["stages"])

    def test_lista_vuota(self):
        self.assertEqual(extract_sleep([]), [])

    def test_punto_malformato_ignorato(self):
        self.assertEqual(extract_sleep([{"boh": 1}]), [])


class ExtractDailyTest(unittest.TestCase):
    def test_hrv(self):
        self.assertEqual(extract_daily_value([DAILY_HRV_POINT]), 44.55)

    def test_rhr_valore_stringa(self):
        # beatsPerMinute arriva come stringa: deve essere convertito
        self.assertEqual(extract_daily_value([DAILY_RHR_POINT]), 53.0)

    def test_spo2(self):
        self.assertEqual(extract_daily_value([DAILY_SPO2_POINT]), 94.8)

    def test_respiratory_rate(self):
        self.assertEqual(extract_daily_value([DAILY_RR_POINT]), 15.8)

    def test_vuoto(self):
        self.assertIsNone(extract_daily_value([]))


class ExtractHrTest(unittest.TestCase):
    def test_hourly_ordinato_per_orario(self):
        out = extract_hr_hourly(HR_ROLLUP)
        self.assertEqual(len(out), 2)
        # 22Z = 00:00 Rome, 23Z = 01:00 Rome — deve uscire ordinato per tempo
        self.assertEqual(out[0], {"hour": "00:00", "bpm": 58.2})
        self.assertEqual(out[1], {"hour": "01:00", "bpm": 55.0})

    def test_stats(self):
        self.assertEqual(extract_hr_stats(HR_DAILY), {"min": 48.0, "avg": 62.0, "max": 132.0})

    def test_stats_vuoto(self):
        self.assertIsNone(extract_hr_stats({}))


class ExtractStepsTest(unittest.TestCase):
    def test_steps_valore_stringa(self):
        self.assertEqual(extract_steps(STEPS_DAILY), 8421)

    def test_vuoto(self):
        self.assertIsNone(extract_steps({}))


# Forme reali dai rollup 900s (probe-activity.json, 2026-07-12)
STEPS_900 = {"rollupDataPoints": [
    {"startTime": "2026-07-12T08:00:00Z", "endTime": "2026-07-12T08:15:00Z",
     "steps": {"countSum": "1375"}},
    {"startTime": "2026-07-12T07:45:00Z", "endTime": "2026-07-12T08:00:00Z",
     "steps": {"countSum": "811"}},
    {"startTime": "2026-07-12T21:00:00Z", "endTime": "2026-07-12T21:15:00Z",
     "steps": {"countSum": "0"}},
]}

HR_900 = {"rollupDataPoints": [
    {"startTime": "2026-07-12T08:00:00Z", "endTime": "2026-07-12T08:15:00Z",
     "heartRate": {"beatsPerMinuteAvg": 88.3, "beatsPerMinuteMax": "99",
                   "beatsPerMinuteMin": 74}},
    {"startTime": "2026-07-12T07:45:00Z", "endTime": "2026-07-12T08:00:00Z",
     "heartRate": {"beatsPerMinuteAvg": "91.5"}},
]}

AZM_POINTS = [
    {"dataSource": {"platform": "FITBIT"},
     "activeZoneMinutes": {
         "interval": {"startTime": "2026-07-12T16:26:00Z"},
         "heartRateZone": "FAT_BURN", "activeZoneMinutes": "1"}},
    {"dataSource": {"platform": "FITBIT"},
     "activeZoneMinutes": {
         "interval": {"startTime": "2026-07-12T16:18:00Z"},
         "heartRateZone": "CARDIO", "activeZoneMinutes": "1"}},
    {"malformed": True},
]


class ExtractStepsIntradayTest(unittest.TestCase):
    def test_ordinato_locale_senza_zero(self):
        out = extract_steps_intraday(STEPS_900)
        # 07:45Z = 09:45 Rome; ordinato per tempo; bucket a 0 escluso
        self.assertEqual(out, [{"time": "09:45", "steps": 811},
                               {"time": "10:00", "steps": 1375}])

    def test_vuoto(self):
        self.assertEqual(extract_steps_intraday({}), [])


class ExtractHrIntradayTest(unittest.TestCase):
    def test_max_min_opzionali(self):
        out = extract_hr_intraday(HR_900)
        self.assertEqual(out[0], {"time": "09:45", "avg": 91.5})
        self.assertEqual(out[1], {"time": "10:00", "avg": 88.3, "max": 99.0, "min": 74.0})

    def test_vuoto(self):
        self.assertEqual(extract_hr_intraday({}), [])


class ExtractAzmTest(unittest.TestCase):
    def test_zone_e_ordinamento(self):
        out = extract_azm(AZM_POINTS)
        self.assertEqual(out, [
            {"time": "18:18", "zone": "CARDIO", "minutes": 1},
            {"time": "18:26", "zone": "FAT_BURN", "minutes": 1},
        ])

    def test_vuoto(self):
        self.assertEqual(extract_azm([]), [])


if __name__ == "__main__":
    unittest.main()
