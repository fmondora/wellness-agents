#!/usr/bin/env python3.12
"""Analisi del sonno — punteggio sul baseline personale dell'utente, non su medie di popolazione.

Google dà un punteggio contro una media di popolazione. Qui il punteggio e la
lettura sono contro il baseline personale (mediana rolling delle notti recenti) e i
suoi target: "DEEP = la tua mediana" dice più di "86/100".

Output: dict strutturato (score + fasi + confronto baseline) + testo pronto per
Telegram/buongiorno. La lettura tantrica/council la aggiunge il Kaula sopra questo.

Uso:
  python3.12 scripts/sleep_analysis.py            # notte di oggi, testo
  python3.12 scripts/sleep_analysis.py --date X   # una data
  python3.12 scripts/sleep_analysis.py --json      # dict grezzo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import os
PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from health_metrics import (DEFAULT_NIGHT_PRACTICE, fitbit_days_back,  # noqa: E402
                            load_fitbit_day, main_sleep_session,
                            night_practice_windows, rmssd_or_none,
                            robust_baseline, sleep_stage_minutes)

TZ = ZoneInfo("Europe/Rome")

# target di riferimento (fallback se manca baseline) — override in config/sleep.json del repo dati
_cfg = {}
_cfg_path = PROJECT_ROOT / "config" / "sleep.json"
if _cfg_path.exists():
    _cfg = json.loads(_cfg_path.read_text())
TARGET_ASLEEP = _cfg.get("target_asleep_min", 420)   # default 7h
TARGET_DEEP = _cfg.get("target_deep_min", 60)
TARGET_REM = _cfg.get("target_rem_min", 100)
BEDTIME_TARGET = _cfg.get("bedtime_target", "22:30")

# soglie della veglia abitata: stesse del detector, lette dal repo dati
_insights_path = PROJECT_ROOT / "config" / "insights.json"
NIGHT_PRACTICE_RULE = dict(DEFAULT_NIGHT_PRACTICE)
if _insights_path.exists():
    NIGHT_PRACTICE_RULE.update(
        (json.loads(_insights_path.read_text()).get("rules") or {}).get("night_practice") or {})

# pesi del punteggio personale (somma 100)
WEIGHTS = {"durata": 25, "efficienza": 20, "deep": 20, "rem": 15, "continuita": 20}


def _pct(x, whole):
    return round(100 * x / whole) if whole else None


def _hhmm_to_min(hhmm):
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _baseline(date_str: str, extractor, days: int = 14):
    hist = fitbit_days_back(days + 1, date_str)[:-1]  # esclude il giorno stesso
    vals = []
    for d in hist:
        s = main_sleep_session(d)
        if not s:
            continue
        v = extractor(d, s)
        if isinstance(v, (int, float)) and v > 0:
            vals.append(v)
    return robust_baseline(vals)


def _score_component(value, reference, cap_full_at_ref=True):
    """0-1: pieno se value >= reference; scala lineare sotto."""
    if not reference:
        return None
    ratio = value / reference
    return min(1.0, ratio) if cap_full_at_ref else ratio


def analyze(date_str: str | None = None) -> dict | None:
    date_str = date_str or datetime.now(TZ).strftime("%Y-%m-%d")
    fitbit = load_fitbit_day(date_str)
    session = main_sleep_session(fitbit)
    if not session:
        return None

    asleep = session.get("minutes_asleep") or 0
    in_bed = session.get("duration_min") or 0
    deep = sleep_stage_minutes(session, "DEEP") or 0
    rem = sleep_stage_minutes(session, "REM") or 0
    light = sleep_stage_minutes(session, "LIGHT") or 0
    awake = sleep_stage_minutes(session, "AWAKE") or 0
    efficiency = _pct(asleep, in_bed)

    # baseline personali (mediana 14 gg)
    base = {
        "asleep": _baseline(date_str, lambda d, s: s.get("minutes_asleep")),
        "deep": _baseline(date_str, lambda d, s: sleep_stage_minutes(s, "DEEP")),
        "rem": _baseline(date_str, lambda d, s: sleep_stage_minutes(s, "REM")),
    }
    med = {k: (round(v["median"]) if v else None) for k, v in base.items()}

    # componenti del punteggio: durata sul TARGET (una notte corta non va scusata
    # da un baseline basso); architettura (deep/rem) sul baseline personale.
    c_dur = _score_component(asleep, TARGET_ASLEEP)
    c_eff = _score_component(efficiency or 0, 95)
    c_deep = _score_component(deep, med["deep"] or TARGET_DEEP)
    c_rem = _score_component(rem, med["rem"] or TARGET_REM)
    # continuità: pieno se svegli <=15 min, zero a >=90 min
    def _continuita(minuti_svegli):
        return max(0.0, min(1.0, (90 - minuti_svegli) / 75)) if minuti_svegli is not None else None

    c_cont = _continuita(awake)

    comps = {"durata": c_dur, "efficienza": c_eff, "deep": c_deep,
             "rem": c_rem, "continuita": c_cont}

    def _score(components):
        total_w = sum(WEIGHTS[k] for k, v in components.items() if v is not None)
        return (round(sum(WEIGHTS[k] * v for k, v in components.items() if v is not None)
                      / total_w * 100) if total_w else None)

    score = _score(comps)

    def _label(value):
        return ("ottimo" if value and value >= 85 else
                "buono" if value and value >= 70 else
                "discreto" if value and value >= 55 else
                "sotto la tua norma" if value is not None else None)

    label = _label(score)

    # Veglia abitata — il risveglio che è diventato pratica. Il punteggio NON si
    # corregge da solo: la firma è un'inferenza, non un fatto. La lettura mostra
    # entrambi i numeri e nomina l'ambiguità; a scioglierla è la risposta, nel log.
    practice = None
    windows = night_practice_windows(fitbit, session, NIGHT_PRACTICE_RULE)
    if windows and awake is not None:
        practice_min = sum(w["minutes"] for w in windows)
        comps_abitata = {**comps, "continuita": _continuita(max(0, awake - practice_min))}
        score_abitata = _score(comps_abitata)
        practice = {"minutes": practice_min, "windows": windows,
                    "awake_involuntary": max(0, awake - practice_min),
                    "score_if_inhabited": score_abitata,
                    "label_if_inhabited": _label(score_abitata)}

    return {
        "date": date_str,
        "score": score,
        "label": label,
        "session": {"start": session.get("start"), "end": session.get("end"),
                    "in_bed_min": in_bed, "asleep_min": asleep, "efficiency": efficiency},
        "stages": {
            "deep": {"min": deep, "pct": _pct(deep, asleep), "baseline": med["deep"]},
            "rem": {"min": rem, "pct": _pct(rem, asleep), "baseline": med["rem"]},
            "light": {"min": light, "pct": _pct(light, asleep)},
            "awake": {"min": awake},
        },
        "night_practice": practice,
        "asleep_baseline": med["asleep"],
        "vitals": {"hrv_rmssd": rmssd_or_none((fitbit or {}).get("hrv_rmssd")),
                   "resting_hr": (fitbit or {}).get("resting_hr"),
                   "respiratory_rate": (fitbit or {}).get("respiratory_rate")},
        "components": {k: (round(v, 2) if v is not None else None) for k, v in comps.items()},
        "bedtime_vs_target": (_hhmm_to_min(session.get("start")) is not None
                              and _hhmm_to_min(session.get("start")) - _hhmm_to_min(BEDTIME_TARGET)),
    }


def _arrow(value, baseline, tol=0.08):
    if value is None or not baseline:
        return ""
    r = value / baseline
    return " ↑" if r >= 1 + tol else " ↓" if r <= 1 - tol else " →"


def format_text(a: dict) -> str:
    s = a["session"]
    st = a["stages"]
    hm = lambda m: f"{m // 60}h{m % 60:02d}"
    lines = [f"😴 Sonno {a['date']} — punteggio {a['score']}/100 ({a['label']})",
             f"{s['start']}–{s['end']} · {hm(s['asleep_min'])} dormite"
             f"{_arrow(s['asleep_min'], a['asleep_baseline'])} · efficienza {s['efficiency']}%"]
    d, r = st["deep"], st["rem"]
    lines.append(f"DEEP {d['min']}m ({d['pct']}%){_arrow(d['min'], d['baseline'])}"
                 f" · REM {r['min']}m ({r['pct']}%){_arrow(r['min'], r['baseline'])}"
                 f" · svegli {st['awake']['min']}m")
    np_ = a.get("night_practice")
    if np_:
        w = max(np_["windows"], key=lambda x: x["minutes"])
        lines.append(f"🪷 {w['start']}–{w['end']} fermo, poi FC a {w['post_level']:.0f} "
                     f"(sotto i {w['pre_level']:.0f} di prima): se quella veglia era abitata "
                     f"il punteggio è {np_['score_if_inhabited']} "
                     f"({np_['label_if_inhabited']}), non {a['score']}. Hai meditato?")
    v = a["vitals"]
    if v["hrv_rmssd"]:
        lines.append(f"HRV {v['hrv_rmssd']:.0f} · FC riposo {v['resting_hr']:.0f}"
                     + (f" · resp {v['respiratory_rate']}" if v["respiratory_rate"] else ""))
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Analisi del sonno (wellness-agents)")
    p.add_argument("--date", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    a = analyze(args.date)
    if a is None:
        print("Nessun dato di sonno per questa data.")
        return 1
    print(json.dumps(a, indent=2, ensure_ascii=False) if args.json else format_text(a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
