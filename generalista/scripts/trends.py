#!/usr/bin/env python3.12
"""Analisi longitudinale: baseline, trend e anomalie su finestre 10/30/90/300 giorni.

Sorgente primaria: data/fitbit/*.json (dati oggettivi omogenei).
Fallback storico HRV: data/logs/*.json → morning.hrv, MA solo dove il valore
è RMSSD in ms (normalize_hrv) — la scala HRV4Training (1-10) resta una serie
separata, mai mischiata.

Output: data/insights/trends.json (+ --print per uso interattivo).

Uso:
  python3.12 scripts/trends.py            # rigenera il file
  python3.12 scripts/trends.py --print    # rigenera e stampa il riepilogo
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import os
PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from health_metrics import (load_fitbit_day, main_sleep_session,  # noqa: E402
                            normalize_hrv, rmssd_or_none, robust_baseline,
                            robust_zscore, sleep_stage_minutes)

TZ = ZoneInfo("Europe/Rome")
LOGS_DIR = PROJECT_ROOT / "data" / "logs"
OUT_FILE = PROJECT_ROOT / "data" / "insights" / "trends.json"

WINDOWS = [10, 30, 90, 300]
ANOMALY_Z = 2.0
# slope relativa (per giorno, in % della mediana) oltre cui il trend non è "→"
SLOPE_REL_THRESHOLD = 0.004

# Coordinate di casa per il calcolo della luce solare — da config/location.json
# del repo dati ({"lat": ..., "lon": ...}); nei giorni di trasferta il campo
# location dei log segnala che il dato va letto con cautela.
_loc_path = PROJECT_ROOT / "config" / "location.json"
if _loc_path.exists():
    _loc = json.loads(_loc_path.read_text())
    HOME_LAT, HOME_LON = _loc["lat"], _loc["lon"]
else:  # default: Roma — imposta config/location.json per la tua casa
    HOME_LAT, HOME_LON = 41.9, 12.5
# soglia passi nella prima ora dopo la sveglia = proxy "uscito presto"
MORNING_LIGHT_STEPS = 300


def _metric_extractors():
    """metrica → funzione(fitbit_day) -> float|None"""
    return {
        "hrv_rmssd": lambda d: rmssd_or_none(d.get("hrv_rmssd")),
        "resting_hr": lambda d: d.get("resting_hr"),
        "minutes_asleep": lambda d: (main_sleep_session(d) or {}).get("minutes_asleep"),
        "deep_min": lambda d: sleep_stage_minutes(main_sleep_session(d), "DEEP"),
        "rem_min": lambda d: sleep_stage_minutes(main_sleep_session(d), "REM"),
        "awake_min": lambda d: sleep_stage_minutes(main_sleep_session(d), "AWAKE"),
        "steps": lambda d: d.get("steps"),
        "respiratory_rate": lambda d: d.get("respiratory_rate"),
        "spo2_avg": lambda d: d.get("spo2_avg"),
    }


def build_series(end_date: str, max_days: int) -> dict[str, list[tuple[str, float]]]:
    """Serie (data, valore) per metrica dagli ultimi max_days file fitbit.

    Fallback HRV storica dai log SOLO per hrv_rmssd e SOLO scala ms; i valori
    HRV4Training finiscono nella serie separata hrv_recovery_points.
    """
    extractors = _metric_extractors()
    series: dict[str, list] = {m: [] for m in extractors}
    series["hrv_recovery_points"] = []

    end = date.fromisoformat(end_date)
    for offset in range(max_days - 1, -1, -1):
        d = (end - timedelta(days=offset)).isoformat()
        fitbit = load_fitbit_day(d)
        if fitbit:
            for metric, fn in extractors.items():
                try:
                    v = fn(fitbit)
                except Exception:
                    v = None
                if isinstance(v, (int, float)):
                    series[metric].append((d, float(v)))

        # fallback log: HRV storica pre-Fitbit (o giorni senza file fitbit)
        if not fitbit or "hrv_rmssd" not in fitbit:
            log_file = LOGS_DIR / f"{d}.json"
            if log_file.exists():
                try:
                    log = json.loads(log_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                raw = (log.get("morning") or {}).get("hrv")
                norm = normalize_hrv(raw)
                if norm is None:
                    continue
                scale, value = norm
                if scale == "rmssd_ms":
                    series["hrv_rmssd"].append((d, value))
                else:
                    series["hrv_recovery_points"].append((d, value))
    return series


def _slope_per_day(points: list[tuple[str, float]]) -> float | None:
    """Slope della regressione lineare valore~giorno (min 4 punti)."""
    if len(points) < 4:
        return None
    x = [(date.fromisoformat(d) - date.fromisoformat(points[0][0])).days
         for d, _ in points]
    y = [v for _, v in points]
    n = len(x)
    mean_x, mean_y = sum(x) / n, sum(y) / n
    denom = sum((xi - mean_x) ** 2 for xi in x)
    if denom == 0:
        return None
    return sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / denom


def _classify(slope: float | None, median: float | None) -> str:
    if slope is None or not median:
        return "?"
    rel = slope / abs(median)
    if rel > SLOPE_REL_THRESHOLD:
        return "↑"
    if rel < -SLOPE_REL_THRESHOLD:
        return "↓"
    return "→"


# ── circadiano ───────────────────────────────────────────────


def solar_times(d: date, lat: float = HOME_LAT, lon: float = HOME_LON) -> dict | None:
    """Alba/tramonto locali (formula NOAA semplificata, precisione ~2 min)."""
    import math
    day_of_year = d.timetuple().tm_yday
    # offset locale (Europe/Rome, DST incluso) per il giorno richiesto
    utc_offset_h = datetime(d.year, d.month, d.day, 12,
                            tzinfo=TZ).utcoffset().total_seconds() / 3600

    gamma = 2 * math.pi / 365 * (day_of_year - 1 + 0.5)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma)
                       - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma)
                       - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat_r = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
              - math.tan(lat_r) * math.tan(decl))
    if not -1 <= cos_ha <= 1:
        return None  # sole di mezzanotte / notte polare
    ha = math.degrees(math.acos(cos_ha))
    def to_local_min(ha_signed):
        utc_min = 720 - 4 * (lon + ha_signed) - eqtime
        return (utc_min + utc_offset_h * 60) % 1440
    sunrise = to_local_min(ha)
    sunset = to_local_min(-ha)
    return {"sunrise": _fmt_clock(sunrise), "sunset": _fmt_clock(sunset),
            "sunrise_min": round(sunrise), "sunset_min": round(sunset),
            "photoperiod_h": round((sunset - sunrise) / 60, 2)}


def _fmt_clock(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _hhmm_min(hhmm: str | None) -> int | None:
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _since_noon(minutes: int) -> int:
    """Minuti dalle 12:00 — evita il wrap di mezzanotte per orari serali/notturni."""
    return (minutes - 720) % 1440


def circadian_analysis(end_date: str, days: int = 30) -> dict:
    """Marker circadiani dagli ultimi `days` giorni di dati fitbit + solare."""
    end = date.fromisoformat(end_date)
    out = {"days_analyzed": days}

    midsleeps, bedtimes, wakes, nadirs, evening_hrs = [], [], [], [], []
    morning_light = {"n": 0, "outside": 0}
    acro_points = []

    for offset in range(days - 1, -1, -1):
        d = (end - timedelta(days=offset)).isoformat()
        fitbit = load_fitbit_day(d)
        if not fitbit:
            continue
        session = main_sleep_session(fitbit)
        if session:
            start_m, end_m = _hhmm_min(session.get("start")), _hhmm_min(session.get("end"))
            dur = session.get("duration_min")
            if start_m is not None and end_m is not None and dur:
                bedtimes.append(_since_noon(start_m))
                wakes.append(end_m)
                midsleeps.append(_since_noon(start_m) + dur / 2)

        # nadir FC notturno: minimo tra mezzanotte e le 08:00
        hourly = fitbit.get("heart_rate_hourly") or []
        night = [(e["hour"], e["bpm"]) for e in hourly
                 if isinstance(e, dict) and e.get("hour", "99") < "08:00"
                 and e.get("bpm") is not None]
        if night:
            hour, bpm = min(night, key=lambda x: x[1])
            nadirs.append((_hhmm_min(hour), bpm))

        # FC serale media 20-22 (l'orologio che riceve — o no — il segnale di quiete)
        evening = [e["bpm"] for e in hourly
                   if isinstance(e, dict) and "20:00" <= e.get("hour", "") <= "22:00"]
        if evening:
            evening_hrs.append((d, round(sum(evening) / len(evening), 1)))

        # proxy luce mattutina + acrofase (solo giorni con passi intraday)
        steps_intra = fitbit.get("steps_intraday") or []
        if steps_intra and session and _hhmm_min(session.get("end")) is not None:
            wake_m = _hhmm_min(session["end"])
            first_hour = sum(b["steps"] for b in steps_intra
                             if wake_m <= (_hhmm_min(b["time"]) or -1) < wake_m + 60)
            morning_light["n"] += 1
            if first_hour >= MORNING_LIGHT_STEPS:
                morning_light["outside"] += 1
        for b in steps_intra:
            m = _hhmm_min(b.get("time"))
            if m is not None:
                acro_points.append((m, b["steps"]))

    def clock_stats(vals_since_noon, label):
        base = robust_baseline(vals_since_noon)
        if not base:
            return None
        return {label: _fmt_clock(base["median"] + 720),
                "iqr_min": round(base["iqr"]), "n": base["n"]}

    if midsleeps:
        out["midsleep"] = clock_stats(midsleeps, "median")
    if bedtimes:
        out["bedtime"] = clock_stats(bedtimes, "median")
    if wakes:
        base = robust_baseline(wakes)
        if base:
            out["wake"] = {"median": _fmt_clock(base["median"]),
                           "iqr_min": round(base["iqr"]), "n": base["n"]}
    if nadirs:
        base = robust_baseline([m for m, _ in nadirs])
        if base:
            out["hr_nadir"] = {"median_time": _fmt_clock(base["median"]),
                               "iqr_min": round(base["iqr"]), "n": base["n"],
                               "median_bpm": robust_baseline([b for _, b in nadirs])["median"]}
    if evening_hrs:
        vals = [v for _, v in evening_hrs]
        base = robust_baseline(vals)
        if base:
            elevated = [{"date": d, "bpm": v} for d, v in evening_hrs
                        if v > base["median"] + 8][-5:]
            out["evening_hr"] = {"median": round(base["median"], 1),
                                 "elevated_recent": elevated, "n": base["n"]}
    if acro_points:
        # acrofase = ora media dell'attività pesata sui passi
        total = sum(s for _, s in acro_points)
        if total:
            acro = sum(m * s for m, s in acro_points) / total
            out["activity_acrophase"] = {"mean_time": _fmt_clock(acro),
                                         "days_with_intraday": morning_light["n"]}
    if morning_light["n"]:
        out["morning_light_proxy"] = {
            "days": morning_light["n"],
            "outside_within_1h_rate": round(morning_light["outside"] / morning_light["n"], 2),
            "note": f"≥{MORNING_LIGHT_STEPS} passi nella prima ora dopo la sveglia"}

    solar = solar_times(end)
    if solar:
        out["solar_today"] = solar
        wake_med = (out.get("wake") or {}).get("median")
        if wake_med:
            gap = _hhmm_min(wake_med) - solar["sunrise_min"]
            out["solar_today"]["wake_vs_sunrise_min"] = gap
    return out


def analyze(end_date: str | None = None) -> dict:
    end_date = end_date or datetime.now(TZ).strftime("%Y-%m-%d")
    series = build_series(end_date, max(WINDOWS))

    out = {"generated_at": datetime.now(TZ).isoformat(),
           "end_date": end_date, "metrics": {}}

    for metric, points in series.items():
        if len(points) < 3:
            continue
        m_out = {"windows": {}, "latest": None, "anomalies_10d": []}
        latest_date, latest_val = points[-1]
        if latest_date == end_date:
            m_out["latest"] = {"date": latest_date, "value": latest_val}

        cutoff30 = (date.fromisoformat(end_date) - timedelta(days=30)).isoformat()
        base30 = robust_baseline([v for d, v in points if d >= cutoff30])

        for w in WINDOWS:
            cutoff = (date.fromisoformat(end_date) - timedelta(days=w)).isoformat()
            win = [(d, v) for d, v in points if d >= cutoff]
            if len(win) < 3:
                continue
            base = robust_baseline([v for _, v in win])
            slope = _slope_per_day(win)
            m_out["windows"][str(w)] = {
                "n": len(win),
                "median": round(base["median"], 1) if base else None,
                "p25": round(base["p25"], 1) if base else None,
                "p75": round(base["p75"], 1) if base else None,
                "slope_per_day": round(slope, 3) if slope is not None else None,
                "trend": _classify(slope, base["median"] if base else None),
            }

        if m_out["latest"] and base30:
            m_out["latest"]["z_vs_30d"] = robust_zscore(latest_val, base30)

        cutoff10 = (date.fromisoformat(end_date) - timedelta(days=10)).isoformat()
        for d, v in points:
            if d < cutoff10:
                continue
            z = robust_zscore(v, base30)
            if z is not None and abs(z) > ANOMALY_Z:
                m_out["anomalies_10d"].append({"date": d, "value": v, "z": z})

        out["metrics"][metric] = m_out

    out["circadian"] = circadian_analysis(end_date)
    return out


def print_summary(trends: dict) -> None:
    print(f"Trends al {trends['end_date']}\n")
    for metric, m in trends["metrics"].items():
        latest = m.get("latest") or {}
        w30 = (m.get("windows") or {}).get("30") or {}
        line = f"{metric:22s}"
        if latest:
            z = latest.get("z_vs_30d")
            line += f" oggi {latest['value']:>7.1f}" + (f" (z={z:+.1f})" if z is not None else "")
        else:
            line += " " * 16
        if w30:
            line += f"   30gg: mediana {w30['median']:>7.1f} · trend {w30['trend']} (n={w30['n']})"
        print(line)
        for a in m.get("anomalies_10d", []):
            print(f"   ⚡ anomalia {a['date']}: {a['value']:.1f} (z={a['z']:+.1f})")

    circ = trends.get("circadian") or {}
    if circ:
        print("\nCircadiano (30gg):")
        if circ.get("midsleep"):
            print(f"  midsleep mediano {circ['midsleep']['median']} (IQR {circ['midsleep']['iqr_min']} min, n={circ['midsleep']['n']})")
        if circ.get("bedtime"):
            print(f"  a letto mediano {circ['bedtime']['median']} (IQR {circ['bedtime']['iqr_min']} min)")
        if circ.get("wake"):
            print(f"  sveglia mediana {circ['wake']['median']} (IQR {circ['wake']['iqr_min']} min)")
        if circ.get("hr_nadir"):
            n = circ["hr_nadir"]
            print(f"  nadir FC mediano {n['median_time']} a {n['median_bpm']:.0f} bpm (IQR {n['iqr_min']} min)")
        if circ.get("evening_hr"):
            e = circ["evening_hr"]
            print(f"  FC serale 20-22 mediana {e['median']}" +
                  (f" — sere alte recenti: {', '.join(x['date'][5:] + ' (' + str(x['bpm']) + ')' for x in e['elevated_recent'])}" if e["elevated_recent"] else ""))
        if circ.get("activity_acrophase"):
            print(f"  acrofase attività {circ['activity_acrophase']['mean_time']} (su {circ['activity_acrophase']['days_with_intraday']} giorni intraday)")
        if circ.get("morning_light_proxy"):
            p = circ["morning_light_proxy"]
            print(f"  luce mattutina (proxy passi): fuori entro 1h nel {p['outside_within_1h_rate']:.0%} dei giorni (n={p['days']})")
        if circ.get("solar_today"):
            s = circ["solar_today"]
            extra = f" · sveglia {s['wake_vs_sunrise_min']:+d} min vs alba" if "wake_vs_sunrise_min" in s else ""
            print(f"  sole oggi: alba {s['sunrise']} tramonto {s['sunset']} ({s['photoperiod_h']}h){extra}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Trends longitudinali Lucia")
    parser.add_argument("--date", default=None, help="data finale (default oggi)")
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args()

    trends = analyze(args.date)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(trends, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Salvato: {OUT_FILE}")
    if args.do_print:
        print()
        print_summary(trends)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
