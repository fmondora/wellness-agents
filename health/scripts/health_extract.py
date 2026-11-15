#!/usr/bin/env python3.12
"""Estrazione: dai dataPoints Google Health API al blocco `fitbit` del log.

Parsing difensivo: le forme dei rollup non sono garantite stabili (API
giovane), quindi ogni campo mancante produce None, mai eccezioni.
Tutti gli orari sono convertiti in Europe/Rome. Alcuni valori numerici
arrivano dall'API come stringhe (es. "beatsPerMinute": "53") e vanno
convertiti.

Le forme reali sono documentate in data/fitbit/probe.json (Task 2).
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Rome")

_NUMERIC_STRING = re.compile(r"^[+-]?\d+(\.\d+)?$")

# Ordine di preferenza per il valore "principale" di un tipo Daily.
_DAILY_PREFERRED_KEYS = (
    "averageHeartRateVariabilityMilliseconds",
    "beatsPerMinute",
    "averagePercentage",
    "breathsPerMinute",
)


def first_number(obj):
    """Primo numero trovato in profondità in dict/liste (pura, ricorsiva).

    Accetta stringhe numeriche (l'API a volte le manda così), ma ignora
    bool e stringhe non numeriche.
    """
    if isinstance(obj, bool):
        return None
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, str):
        if _NUMERIC_STRING.match(obj.strip()):
            return float(obj)
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            n = first_number(v)
            if n is not None:
                return n
        return None
    if isinstance(obj, list):
        for v in obj:
            n = first_number(v)
            if n is not None:
                return n
        return None
    return None


def _to_int(value) -> int | None:
    n = first_number(value)
    return int(n) if n is not None else None


def _local_hhmm(iso: str) -> str | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt.astimezone(TZ).strftime("%H:%M")


def _to_utc_datetime(iso: str):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def extract_sleep(points: list) -> list:
    """Sessioni di sonno: orari locali, durata, riepilogo fasi se presente.

    `duration_min` è la durata dell'intera finestra dell'intervallo (non
    solo il sonno effettivo). `minutes_asleep` e `stages` derivano da
    `sleep.summary` quando presente (stagesSummary, non la timeline grezza).
    """
    sessions = []
    for point in points:
        record = point.get("sleep") if isinstance(point, dict) else None
        if not isinstance(record, dict):
            continue
        interval = record.get("interval")
        if not isinstance(interval, dict):
            continue
        start, end = interval.get("startTime"), interval.get("endTime")
        if not start or not end:
            continue
        t0, t1 = _to_utc_datetime(start), _to_utc_datetime(end)
        if t0 is None or t1 is None:
            continue

        session = {
            "start": _local_hhmm(start),
            "end": _local_hhmm(end),
            "duration_min": round((t1 - t0).total_seconds() / 60),
            "minutes_asleep": None,
            "stages": None,
        }

        summary = record.get("summary")
        if isinstance(summary, dict):
            session["minutes_asleep"] = _to_int(summary.get("minutesAsleep"))
            stages_summary = summary.get("stagesSummary")
            if isinstance(stages_summary, list):
                stages = []
                for stage in stages_summary:
                    if not isinstance(stage, dict):
                        continue
                    stages.append({
                        "type": stage.get("type"),
                        "minutes": _to_int(stage.get("minutes")),
                        "count": _to_int(stage.get("count")),
                    })
                if stages:
                    session["stages"] = stages

        sessions.append(session)
    return sessions


def extract_daily_value(points: list) -> float | None:
    """Valore numerico di un tipo Daily (HRV, SpO2, RR, RHR).

    Preferisce le chiavi note del tipo (averageHeartRateVariabilityMilliseconds,
    beatsPerMinute, averagePercentage, breathsPerMinute); altrimenti cerca il
    primo numero nel record scartando il campo `date`.
    """
    for point in points:
        if not isinstance(point, dict):
            continue
        for key, record in point.items():
            if key in ("name", "dataSource") or not isinstance(record, dict):
                continue

            for preferred in _DAILY_PREFERRED_KEYS:
                if preferred in record:
                    n = first_number(record[preferred])
                    if n is not None:
                        return round(n, 2)

            cleaned = {k: v for k, v in record.items() if k != "date"}
            n = first_number(cleaned)
            if n is not None:
                return round(n, 2)
    return None


def extract_hr_hourly(rollup: dict) -> list:
    """Frequenza cardiaca media per ora locale, ordinata cronologicamente.

    Legge `rollupDataPoints` (startTime top-level, heartRate.beatsPerMinuteAvg).
    L'ordine dell'API non è garantito: si ordina esplicitamente per istante.
    """
    if not isinstance(rollup, dict):
        return []
    entries = []
    for bucket in rollup.get("rollupDataPoints", []) or []:
        if not isinstance(bucket, dict):
            continue
        start = bucket.get("startTime")
        heart_rate = bucket.get("heartRate")
        if not isinstance(start, str) or not isinstance(heart_rate, dict):
            continue
        bpm = first_number(heart_rate.get("beatsPerMinuteAvg"))
        if bpm is None:
            continue
        dt = _to_utc_datetime(start)
        hour = _local_hhmm(start)
        if dt is None or hour is None:
            continue
        entries.append((dt, {"hour": hour, "bpm": round(bpm, 1)}))
    entries.sort(key=lambda entry: entry[0])
    return [entry[1] for entry in entries]


def extract_hr_stats(daily_rollup: dict) -> dict | None:
    """min/avg/max dal dailyRollup di heart-rate, se presenti."""
    if not isinstance(daily_rollup, dict):
        return None
    mapping = {"min": "beatsPerMinuteMin", "avg": "beatsPerMinuteAvg", "max": "beatsPerMinuteMax"}
    for bucket in daily_rollup.get("rollupDataPoints", []) or []:
        if not isinstance(bucket, dict):
            continue
        heart_rate = bucket.get("heartRate")
        if not isinstance(heart_rate, dict):
            continue
        stats = {}
        for out_key, src_key in mapping.items():
            n = first_number(heart_rate.get(src_key))
            if n is not None:
                stats[out_key] = round(n, 1)
        if stats:
            return stats
    return None


def extract_steps_intraday(rollup: dict) -> list:
    """Passi per bucket (es. 900s), ora locale, ordinati. Bucket a 0 esclusi.

    Legge `rollupDataPoints` (startTime top-level, steps.countSum).
    """
    if not isinstance(rollup, dict):
        return []
    entries = []
    for bucket in rollup.get("rollupDataPoints", []) or []:
        if not isinstance(bucket, dict):
            continue
        start = bucket.get("startTime")
        steps = bucket.get("steps")
        if not isinstance(start, str) or not isinstance(steps, dict):
            continue
        n = first_number(steps.get("countSum"))
        if n is None or n <= 0:
            continue
        dt = _to_utc_datetime(start)
        time_local = _local_hhmm(start)
        if dt is None or time_local is None:
            continue
        entries.append((dt, {"time": time_local, "steps": int(n)}))
    entries.sort(key=lambda entry: entry[0])
    return [entry[1] for entry in entries]


def extract_hr_intraday(rollup: dict) -> list:
    """FC per bucket (es. 900s): avg sempre, max/min se presenti. Ora locale, ordinati."""
    if not isinstance(rollup, dict):
        return []
    entries = []
    for bucket in rollup.get("rollupDataPoints", []) or []:
        if not isinstance(bucket, dict):
            continue
        start = bucket.get("startTime")
        heart_rate = bucket.get("heartRate")
        if not isinstance(start, str) or not isinstance(heart_rate, dict):
            continue
        avg = first_number(heart_rate.get("beatsPerMinuteAvg"))
        if avg is None:
            continue
        dt = _to_utc_datetime(start)
        time_local = _local_hhmm(start)
        if dt is None or time_local is None:
            continue
        entry = {"time": time_local, "avg": round(avg, 1)}
        for out_key, src_key in (("max", "beatsPerMinuteMax"), ("min", "beatsPerMinuteMin")):
            n = first_number(heart_rate.get(src_key))
            if n is not None:
                entry[out_key] = round(n, 1)
        entries.append((dt, entry))
    entries.sort(key=lambda entry: entry[0])
    return [entry[1] for entry in entries]


def extract_azm(points: list) -> list:
    """Active Zone Minutes: punti al minuto con zona cardio, ora locale, ordinati.

    Forma reale (probe-activity.json): point.activeZoneMinutes con
    interval.startTime, heartRateZone (FAT_BURN/CARDIO/PEAK), activeZoneMinutes ("1").
    """
    entries = []
    for point in points:
        record = point.get("activeZoneMinutes") if isinstance(point, dict) else None
        if not isinstance(record, dict):
            continue
        interval = record.get("interval")
        if not isinstance(interval, dict):
            continue
        start = interval.get("startTime")
        if not isinstance(start, str):
            continue
        dt = _to_utc_datetime(start)
        time_local = _local_hhmm(start)
        if dt is None or time_local is None:
            continue
        minutes = _to_int(record.get("activeZoneMinutes"))
        entries.append((dt, {
            "time": time_local,
            "zone": record.get("heartRateZone"),
            "minutes": minutes if minutes is not None else 1,
        }))
    entries.sort(key=lambda entry: entry[0])
    return [entry[1] for entry in entries]


def extract_steps(daily_rollup: dict) -> int | None:
    """Totale passi dal dailyRollup di steps (rollupDataPoints[].steps.countSum)."""
    if not isinstance(daily_rollup, dict):
        return None
    for bucket in daily_rollup.get("rollupDataPoints", []) or []:
        if not isinstance(bucket, dict):
            continue
        steps = bucket.get("steps")
        if not isinstance(steps, dict):
            continue
        n = first_number(steps.get("countSum"))
        if n is not None:
            return int(n)
    return None


def extract_sleep_temperature(points: list) -> dict | None:
    """Temperatura cutanea della notte (`daily-sleep-temperature-derivations`, Fitbit).

    → {"nightly_c", "baseline_c"?, "delta_c"?, "sd30_c"?}: `delta_c` = notte − baseline personale
    (mediana dei 30 giorni, la calcola Google), `sd30_c` = deviazione standard dello scostamento a
    30 giorni. È temperatura della pelle, non febbre: conta lo scostamento, non il valore.
    """
    for point in points:
        rec = (point or {}).get("dailySleepTemperatureDerivations") if isinstance(point, dict) else None
        if not isinstance(rec, dict):
            continue
        night = _num(rec.get("nightlyTemperatureCelsius"))   # a volte arriva come stringa
        if night is None:
            continue
        out = {"nightly_c": round(night, 2)}
        base = _num(rec.get("baselineTemperatureCelsius"))
        if base is not None:
            out["baseline_c"] = round(base, 2)
            out["delta_c"] = round(night - base, 2)
        sd = _num(rec.get("relativeNightlyStddev30dCelsius"))
        if sd is not None:
            out["sd30_c"] = round(sd, 2)
        return out
    return None


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sample_time(rec: dict) -> str:
    st = rec.get("sampleTime") or {}
    return str(st.get("physicalTime") or st.get("civilTime") or "")


def extract_body(weight_points: list, fat_points: list) -> dict:
    """Ultima misura del giorno da bilancia (o inserita a mano): {"weight_kg"?, "body_fat_pct"?, "body_source"?}."""
    out: dict = {}
    ws = [(p or {}).get("weight") for p in weight_points if isinstance(p, dict)]
    ws = [w for w in ws if isinstance(w, dict) and _num(w.get("weightGrams")) is not None]
    if ws:
        last = max(ws, key=_sample_time)
        out["weight_kg"] = round(_num(last["weightGrams"]) / 1000, 2)
        src = next((p.get("dataSource") for p in weight_points
                    if isinstance(p, dict) and p.get("weight") is last), None) or {}
        name = (src.get("device") or {}).get("displayName") or src.get("platform")
        if name:
            out["body_source"] = name
    fs = [(p or {}).get("bodyFat") for p in fat_points if isinstance(p, dict)]
    fs = [f for f in fs if isinstance(f, dict) and _num(f.get("percentage")) is not None]
    if fs:
        out["body_fat_pct"] = round(_num(max(fs, key=_sample_time)["percentage"]), 1)
    return out



# --- attività, calorie e notte: i tipi aggiunti il 15/11/2026 ---------------------------

def _rollup_record(daily_rollup: dict, key: str) -> dict | None:
    """Il record `key` del primo bucket di un dailyRollup ({} se il giorno non ha dati)."""
    if not isinstance(daily_rollup, dict):
        return None
    for bucket in daily_rollup.get("rollupDataPoints", []) or []:
        if isinstance(bucket, dict) and isinstance(bucket.get(key), dict):
            return bucket[key]
    return None


def _seconds(v) -> float | None:
    """'44520s' → 44520.0"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.endswith("s"):
        try:
            return float(v[:-1])
        except ValueError:
            return None
    return None


def _zone_key(z: str) -> str:
    return str(z or "").lower() or "?"


def extract_calories(total_roll: dict, active_roll: dict, zone_roll: dict) -> dict | None:
    """Calorie del giorno: totali (metabolismo compreso), attive, e per zona di frequenza."""
    out: dict = {}
    t = _rollup_record(total_roll, "totalCalories")
    if t and (n := _num(t.get("kcalSum"))) is not None:
        out["total"] = int(round(n))
    a = _rollup_record(active_roll, "activeEnergyBurned")
    if a and (n := _num(a.get("kcalSum"))) is not None:
        out["active"] = int(round(n))
    if "total" in out and "active" in out:
        out["resting"] = out["total"] - out["active"]
    z = _rollup_record(zone_roll, "caloriesInHeartRateZone")
    if z:
        zones = {_zone_key(x.get("heartRateZone")): int(round(_num(x.get("kcal")) or 0))
                 for x in z.get("caloriesInHeartRateZones") or [] if isinstance(x, dict)}
        if zones:
            out["by_hr_zone"] = zones
    return out or None


def extract_distance_km(roll: dict) -> float | None:
    r = _rollup_record(roll, "distance")
    n = _num(r.get("millimetersSum")) if r else None
    return round(n / 1_000_000, 2) if n is not None else None


def extract_count(roll: dict, key: str) -> int | None:
    r = _rollup_record(roll, key)
    n = _num(r.get("countSum")) if r else None
    return int(n) if n is not None else None


def extract_sedentary_min(roll: dict) -> int | None:
    r = _rollup_record(roll, "sedentaryPeriod")
    s = _seconds(r.get("durationSum")) if r else None
    return int(round(s / 60)) if s is not None else None


def extract_active_minutes(roll: dict) -> dict | None:
    """Minuti attivi per livello: {"light": 125, "moderate": 9, "vigorous": 0}."""
    r = _rollup_record(roll, "activeMinutes")
    if not r:
        return None
    out = {}
    for x in r.get("activeMinutesRollupByActivityLevel") or []:
        if isinstance(x, dict) and (n := _num(x.get("activeMinutesSum"))) is not None:
            out[_zone_key(x.get("activityLevel"))] = int(n)
    return out or None


def extract_hr_zone_minutes(roll: dict) -> dict | None:
    """Minuti passati in ogni zona di frequenza nel giorno."""
    r = _rollup_record(roll, "timeInHeartRateZone")
    if not r:
        return None
    out = {}
    for x in r.get("timeInHeartRateZones") or []:
        if isinstance(x, dict) and (s := _seconds(x.get("duration"))) is not None:
            out[_zone_key(x.get("heartRateZone"))] = int(round(s / 60))
    return out or None


def extract_hr_zones(points: list) -> dict | None:
    """Le soglie delle zone del giorno: {"light": [30, 98], "moderate": [99, 121], ...}."""
    for p in points or []:
        rec = p.get("dailyHeartRateZones") if isinstance(p, dict) else None
        if not isinstance(rec, dict):
            continue
        out = {}
        for z in rec.get("heartRateZones") or []:
            if isinstance(z, dict):
                lo, hi = _num(z.get("minBeatsPerMinute")), _num(z.get("maxBeatsPerMinute"))
                if lo is not None and hi is not None:
                    out[_zone_key(z.get("heartRateZoneType"))] = [int(lo), int(hi)]
        if out:
            return out
    return None


def extract_exercises(points: list) -> list:
    """Gli allenamenti riconosciuti o registrati: orari locali, tipo, calorie, passi, FC media, AZM."""
    out = []
    for p in points or []:
        e = p.get("exercise") if isinstance(p, dict) else None
        if not isinstance(e, dict):
            continue
        iv = e.get("interval") or {}
        m = e.get("metricsSummary") or {}
        row = {"start": _local_hhmm(iv.get("startTime") or ""), "end": _local_hhmm(iv.get("endTime") or ""),
               "type": str(e.get("exerciseType") or "").lower(),
               "recorded": str((p.get("dataSource") or {}).get("recordingMethod") or "").lower()}
        for src, dst, conv in (("caloriesKcal", "kcal", int), ("steps", "steps", int),
                               ("averageHeartRateBeatsPerMinute", "avg_hr", int), ("activeZoneMinutes", "azm", int)):
            n = _num(m.get(src))
            if n is not None:
                row[dst] = conv(n)
        d = _num(m.get("distanceMillimeters"))
        if d:
            row["km"] = round(d / 1_000_000, 2)
        if row["start"]:
            out.append(row)
    return sorted(out, key=lambda r: r["start"])


def _civil_hhmm(sample_time: dict) -> str | None:
    t = ((sample_time or {}).get("civilTime") or {}).get("time") or {}
    if "hours" not in t and "minutes" not in t:
        return _local_hhmm((sample_time or {}).get("physicalTime") or "")
    return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"


def extract_hrv_samples(points: list) -> list:
    """HRV della notte a campioni (ogni 5′): [["23:55", 43.5], ...]."""
    out = []
    for p in points or []:
        r = p.get("heartRateVariability") if isinstance(p, dict) else None
        if not isinstance(r, dict):
            continue
        v = _num(r.get("rootMeanSquareOfSuccessiveDifferencesMilliseconds"))
        hm = _civil_hhmm(r.get("sampleTime"))
        if v is not None and hm:
            out.append([hm, round(v, 1)])
    return sorted(out)


def extract_spo2_summary(points: list) -> dict | None:
    """Ossigeno nel sangue durante la notte: minimo, mediana, quanti campioni sotto 90% e sotto 88%.
    (Un dato da osservare, non da interpretare da soli: l'apnea sospetta è una questione del medico.)"""
    vals = []
    for p in points or []:
        r = p.get("oxygenSaturation") if isinstance(p, dict) else None
        if isinstance(r, dict) and (v := _num(r.get("percentage"))) is not None and 50 <= v <= 100:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return {"min": round(vals[0], 1), "median": round(med, 1), "samples": len(vals),
            "below_90": sum(1 for v in vals if v < 90), "below_88": sum(1 for v in vals if v < 88)}


def extract_respiratory_by_stage(points: list) -> dict | None:
    """Respiri al minuto nella notte per fase del sonno (la sessione principale: quella con più segnale)."""
    best, best_snr = None, -1.0
    for p in points or []:
        r = p.get("respiratoryRateSleepSummary") if isinstance(p, dict) else None
        if not isinstance(r, dict):
            continue
        snr = _num((r.get("fullSleepStats") or {}).get("signalToNoise")) or 0
        if snr > best_snr:
            best, best_snr = r, snr
    if not best:
        return None
    out = {}
    for key, name in (("fullSleepStats", "full"), ("deepSleepStats", "deep"), ("lightSleepStats", "light"),
                      ("remSleepStats", "rem")):
        v = _num((best.get(key) or {}).get("breathsPerMinute"))
        if v:
            out[name] = round(v, 1)
    return out or None


def extract_vo2_max(points: list) -> float | None:
    """VO2 max del giorno (stima del dispositivo), se c'è."""
    for p in points or []:
        if not isinstance(p, dict):
            continue
        for key in ("dailyVo2Max", "vo2Max", "runVo2Max"):
            r = p.get(key)
            if isinstance(r, dict):
                for k in ("vo2Max", "vo2MaxMlPerKgPerMinute", "value"):
                    n = _num(r.get(k))
                    if n:
                        return round(n, 1)
                n = first_number({k: v for k, v in r.items() if k not in ("date", "sampleTime")})
                if n and 10 < n < 90:
                    return round(n, 1)
    return None


def extract_height_cm(points: list) -> float | None:
    for p in reversed(points or []):
        r = p.get("height") if isinstance(p, dict) else None
        if isinstance(r, dict):
            for k in ("heightMillimeters", "millimeters"):
                n = _num(r.get(k))
                if n:
                    return round(n / 10, 1)
            n = _num(r.get("heightMeters")) or _num(r.get("meters"))
            if n:
                return round(n * 100, 1)
    return None
