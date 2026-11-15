"""I tipi di dato aggiunti il 15/11/2026: calorie, distanza, piani, minuti attivi e sedentari, zone,
allenamenti, HRV della notte, ossigeno, respiro per fase. Fixture: risposte vere dell'API (14/11)."""
import json
from pathlib import Path

import health_extract as hx

FX = json.loads((Path(__file__).parent / "fixtures" / "activity_2026-11-14.json").read_text())


def test_calorie_del_giorno():
    c = hx.extract_calories(FX["total-calories"], FX["active-energy-burned"], FX["calories-in-heart-rate-zone"])
    assert c == {"total": 2291, "active": 212, "resting": 2079, "by_hr_zone": {"light": 2108, "moderate": 37}}
    assert hx.extract_calories({}, {}, {}) is None
    assert hx.extract_calories(FX["total-calories"], {}, {}) == {"total": 2291}


def test_movimento_del_giorno():
    assert hx.extract_distance_km(FX["distance"]) == 2.44
    assert hx.extract_count(FX["floors"], "floors") == 3
    assert hx.extract_sedentary_min(FX["sedentary-period"]) == 742
    assert hx.extract_active_minutes(FX["active-minutes"]) == {"light": 125, "moderate": 9}
    assert hx.extract_hr_zone_minutes(FX["time-in-heart-rate-zone"]) == {"light": 1311, "moderate": 9}
    assert hx.extract_distance_km(FX["altitude"]) is None                  # rollup vuoto: niente


def test_zone_hrv_ossigeno_respiro():
    assert hx.extract_hr_zones(FX["daily-heart-rate-zones"]) == \
        {"light": [30, 98], "moderate": [99, 121], "vigorous": [122, 149], "peak": [150, 220]}
    hrv = hx.extract_hrv_samples(FX["heart-rate-variability"])
    assert len(hrv) == 4 and hrv == sorted(hrv) and all(len(x) == 2 and ":" in x[0] for x in hrv)
    s = hx.extract_spo2_summary(FX["oxygen-saturation"])
    assert s["samples"] == 6 and s["min"] <= s["median"] and s["below_90"] >= 0
    assert hx.extract_spo2_summary([{"oxygenSaturation": {"percentage": 87.5}}, {"oxygenSaturation": {"percentage": 95}}]) == \
        {"min": 87.5, "median": 91.2, "samples": 2, "below_90": 1, "below_88": 1}
    assert hx.extract_respiratory_by_stage(FX["respiratory-rate-sleep-summary"])["full"] > 10


def test_allenamenti():
    pts = [{"dataSource": {"recordingMethod": "PASSIVELY_MEASURED"},
            "exercise": {"interval": {"startTime": "2026-11-14T15:04:48Z", "endTime": "2026-11-14T15:19:58Z"},
                         "exerciseType": "WALKING",
                         "metricsSummary": {"caloriesKcal": 75, "distanceMillimeters": 520200, "steps": "701",
                                            "averageHeartRateBeatsPerMinute": "91", "activeZoneMinutes": "1"}}},
           {"exercise": {"interval": {}}}, "x"]
    assert hx.extract_exercises(pts) == [{"start": "16:04", "end": "16:19", "type": "walking", "recorded": "passively_measured",
                                          "kcal": 75, "steps": 701, "avg_hr": 91, "azm": 1, "km": 0.52}]


def test_vo2_e_altezza_quando_ci_sono():
    assert hx.extract_vo2_max([{"dailyVo2Max": {"date": {"year": 2026}, "vo2Max": 41.27}}]) == 41.3
    assert hx.extract_vo2_max([]) is None
    assert hx.extract_height_cm([{"height": {"heightMillimeters": 1820}}]) == 182.0
