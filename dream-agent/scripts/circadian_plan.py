#!/usr/bin/env python3.12
"""Piano circadiano: ora di letto consigliata (sera) + ora di sveglia ciclo-allineata.

Il problema di Francesco: vuole svegliarsi ~06:00, ma il ritmo dipende da quando
si addormenta. La leva non è la sveglia — è l'ora di letto. I cicli durano ~90 min;
ci si sveglia freschi se il target cade a FINE ciclo, non nel mezzo.

- SERA: dato il target di sveglia, consiglia l'ora di essere addormentato.
- MATTINA: dato l'addormentamento reale (dai dati Fitbit) o quello previsto,
  calcola la sveglia ciclo-allineata più vicina al target, dentro una finestra.

Consumato da: DreamAgent (piano del sonno), messaggio della sera di Hṛdaya (ora di
letto) e Scorciatoie iOS (endpoint /webhook/circadian del ricevitore di health). NB: la durata del ciclo è un'approssimazione
(varia 80-110 min); la Smart Wake del Fitbit rifinisce il minuto sul sonno leggero.

Uso (cwd o WELLNESS_DATA sul repo dati; soglie in config/insights.json → circadian):
  python3.12 circadian_plan.py --evening   # consiglio ora di letto
  python3.12 circadian_plan.py --morning    # sveglia ciclo-allineata
  python3.12 circadian_plan.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_fitbit_day(date_str: str) -> dict | None:
    try:
        from health_metrics import load_fitbit_day as f  # shim del repo dati o plugin health
    except ImportError:
        from _plugins import import_from
        f = import_from("health", "health_metrics").load_fitbit_day
    return f(date_str)


def main_sleep_session(fitbit_day: dict | None) -> dict | None:
    """La sessione di sonno principale (la più lunga) — stessa regola di health_metrics."""
    valid = [s for s in (fitbit_day or {}).get("sleep") or [] if isinstance(s, dict) and s.get("minutes_asleep")]
    return max(valid, key=lambda s: s["minutes_asleep"]) if valid else None


TZ = ZoneInfo(os.environ.get("WELLNESS_TZ", "Europe/Rome"))
CONFIG = PROJECT_ROOT / "config" / "insights.json"

DEFAULTS = {
    "target_wake": "06:00",
    "cycle_min": 90,
    "onset_latency_min": 15,
    "cycles_options": [5, 4],   # ideale 5 cicli ≈ 7h30 · se fai tardi 4 ≈ 6h (entrambi a fine ciclo)
    "wake_window_before_min": 40,
    "wake_window_after_min": 20,
}


def _cfg() -> dict:
    try:
        c = json.loads(CONFIG.read_text(encoding="utf-8")).get("circadian") or {}
    except Exception:
        c = {}
    return {**DEFAULTS, **c}


WEEKDAYS_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def therapy_reminders(now: datetime | None = None) -> list[str]:
    """Promemoria terapie serali, ancorati a GIORNI NOMINATI.

    Una posologia "3 volte a settimana" non dice quali sere: ogni sera torna
    a essere una decisione da prendere da zero, e nelle settimane storte salta.
    Qui i giorni sono espliciti e il promemoria viaggia dentro il nudge serale
    che esiste già — stesso momento della giornata, un messaggio solo.

    Non è una prescrizione: giorni e orario si concordano col medico, qui si
    ricorda soltanto quello che è già stato deciso.
    """
    now = now or datetime.now(TZ)
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8")).get("therapy_nudge") or {}
    except Exception:
        return []
    if not cfg.get("enabled"):
        return []
    today = WEEKDAYS_IT[now.weekday()]
    return [item["text"] for item in cfg.get("items") or []
            if item.get("text") and today in (item.get("days") or [])]


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt(minutes: int) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def evening_plan(cfg: dict | None = None) -> dict:
    cfg = cfg or _cfg()
    wake = _to_min(cfg["target_wake"])
    cycle = cfg["cycle_min"]
    latency = cfg["onset_latency_min"]
    options = []
    for n in cfg["cycles_options"]:
        asleep_needed = n * cycle
        bedtime = (wake - asleep_needed - latency) % 1440
        options.append({"cycles": n, "bedtime": _fmt(bedtime),
                        "sleep_hours": round(asleep_needed / 60, 1)})
    primary, late = options[0], options[-1]
    reminders = therapy_reminders()
    return {
        "type": "evening",
        "target_wake": cfg["target_wake"],
        "recommended_bedtime": primary["bedtime"],
        "options": options,
        "text": (f"🌙 Sveglia target {cfg['target_wake']}. Due orari di letto, "
                 f"entrambi a fine ciclo:\n"
                 f"• Ideale: {primary['bedtime']} ({primary['sleep_hours']}h, "
                 f"{primary['cycles']} cicli)\n"
                 f"• Se fai tardi: {late['bedtime']} ({late['sleep_hours']}h, "
                 f"{late['cycles']} cicli)\n"
                 f"Meglio {late['bedtime']} che mezzanotte — salteresti un ciclo. "
                 f"Telefono in carica lontano dal letto."
                 + ("\n\n" + "\n".join(reminders) if reminders else "")),
        "therapy_reminders": reminders,
    }


def _detect_onset_min(date_str: str, cfg: dict) -> tuple[int | None, str]:
    """Addormentamento reale (fitbit) o previsto (ora di letto consigliata)."""
    fitbit = load_fitbit_day(date_str)
    session = main_sleep_session(fitbit)
    if session and session.get("start"):
        return _to_min(session["start"]) + cfg["onset_latency_min"], "reale"
    bedtime = _to_min(evening_plan(cfg)["recommended_bedtime"])
    return bedtime + cfg["onset_latency_min"], "previsto"


def morning_plan(date_str: str | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or _cfg()
    date_str = date_str or datetime.now(TZ).strftime("%Y-%m-%d")
    target = _to_min(cfg["target_wake"])
    cycle = cfg["cycle_min"]
    onset, source = _detect_onset_min(date_str, cfg)

    # candidati di sveglia = fine di ogni ciclo dall'addormentamento
    lo = target - cfg["wake_window_before_min"]
    hi = target + cfg["wake_window_after_min"]
    best, best_dist = None, None
    for n in range(1, 12):
        boundary = onset + n * cycle
        # normalizza nell'intorno del target (stesso "giorno" logico)
        b = boundary % 1440
        if lo <= b <= hi:
            dist = abs(b - target)
            if best is None or dist < best_dist:
                best, best_dist = b, dist
    wake = best if best is not None else target
    return {
        "type": "morning",
        "wake": _fmt(wake),
        "target_wake": cfg["target_wake"],
        "cycle_aligned": best is not None,
        "onset_source": source,
        "text": (f"⏰ Sveglia ciclo-allineata: {_fmt(wake)} "
                 f"(addormentamento {source}). La Smart Wake del Fitbit rifinisce "
                 f"sul sonno leggero."),
    }


def full_plan(date_str: str | None = None) -> dict:
    cfg = _cfg()
    return {"generated_at": datetime.now(TZ).isoformat(),
            "evening": evening_plan(cfg),
            "morning": morning_plan(date_str, cfg)}


def main() -> int:
    p = argparse.ArgumentParser(description="Piano circadiano (DreamAgent)")
    p.add_argument("--evening", action="store_true")
    p.add_argument("--morning", action="store_true")
    p.add_argument("--date", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.json:
        print(json.dumps(full_plan(args.date), indent=2, ensure_ascii=False))
    elif args.morning:
        print(morning_plan(args.date)["text"])
    else:
        print(evening_plan()["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
