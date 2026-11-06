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
