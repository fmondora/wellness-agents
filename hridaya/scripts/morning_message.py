#!/usr/bin/env python3.12
"""Fallback deterministici dei due messaggi programmati di Hṛdaya — senza LLM.

I testi veri li scrive la sessione accesa (Hṛdaya, con la meditazione del Kaula la sera
e `/sonno` al mattino). Quando la sessione non c'è, il cancello (`push_gate.tick`) manda
questi, marcati come automatici, così le scadenze non si perdono:

  mattino (dopo l'alzata): notte (orari, ore dormite, DEEP/REM vs 7 giorni), HRV e FC a
                           riposo, eventi del detector rimasti per il mattino, scadenze 48 h
  sera:                    ora di letto, promemoria terapie già decisi, prelievo domani

La meditazione della sera arriva SOLO dalla sessione (il Kaula non si imita).

    morning_message.py [--wake | --evening] [--date YYYY-MM-DD] [--print]

Senza --print il testo passa dal cancello (idempotente: un messaggio al giorno per tipo).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
PRELIEVO = re.compile(r"prelie|esami del sangue|analisi del sangue|emocromo", re.I)


def _root() -> Path:
    return cc.data_root()


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- notte ---------------------------------------------------------------------------

def _main_sleep(day: dict | None) -> dict | None:
    valid = [s for s in (day or {}).get("sleep") or [] if isinstance(s, dict) and s.get("minutes_asleep")]
    return max(valid, key=lambda s: s["minutes_asleep"]) if valid else None


def _stage(session: dict | None, kind: str) -> int | None:
    for st in (session or {}).get("stages") or []:
        if isinstance(st, dict) and st.get("type") == kind:
            return st.get("minutes")
    return None


def _rmssd(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("rmssd") or v.get("dailyRmssd") or v.get("value")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 12 else None   # sotto 12 non è RMSSD in ms (scala Recovery Points)


def _arrow(value, med, tol=0.08) -> str:
    if value is None or not med:
        return ""
    r = value / med
    return " ↑" if r >= 1 + tol else " ↓" if r <= 1 - tol else " →"


def _hm(minutes) -> str:
    return "?" if minutes is None else f"{int(minutes) // 60}h{int(minutes) % 60:02d}"


def night_lines(day: str) -> list[str]:
    fit = _root() / "data" / "fitbit"
    today = _json(fit / f"{day}.json")
    s = _main_sleep(today)
    hist = [_json(fit / f"{(date.fromisoformat(day) - timedelta(days=i)).isoformat()}.json") for i in range(1, 8)]

    def med(fn):
        vals = [v for v in (fn(h) for h in hist if h) if isinstance(v, (int, float))]
        return statistics.median(vals) if len(vals) >= 3 else None

    out = []
    if s:
        asleep = s.get("minutes_asleep")
        out.append(f"😴 {s.get('start')}–{s.get('end')} · {_hm(asleep)} dormite"
                   f"{_arrow(asleep, med(lambda h: (_main_sleep(h) or {}).get('minutes_asleep')))}")
        det = []
        for k, lab in (("DEEP", "DEEP"), ("REM", "REM")):
            v = _stage(s, k)
            if v is not None:
                det.append(f"{lab} {v}m{_arrow(v, med(lambda h, k=k: _stage(_main_sleep(h), k)))}")
        aw = _stage(s, "AWAKE")
        if aw is not None:
            det.append(f"svegli {aw}m")
        if det:
            out.append("   " + " · ".join(det))
    else:
        out.append("😴 I dati della notte non sono ancora arrivati.")
    hrv = _rmssd((today or {}).get("hrv_rmssd"))
    rhr = (today or {}).get("resting_hr")
    if hrv is not None:
        out.append(f"❤️ HRV {hrv:.0f}{_arrow(hrv, med(lambda h: _rmssd(h.get('hrv_rmssd'))))}"
                   + (f" · FC a riposo {float(rhr):.0f}" if rhr else ""))
    elif rhr:
        out.append(f"❤️ FC a riposo {float(rhr):.0f}")
    return out


def morning_events(day: str, mark: bool = True) -> list[str]:
    """Eventi del detector con deliver=morning non consegnati (oggi e ieri), marcati consegnati."""
    evdir = _root() / "data" / "insights" / "events"
    out = []
    for d in (day, (date.fromisoformat(day) - timedelta(days=1)).isoformat()):
        f = evdir / f"{d}.jsonl"
        if not f.exists():
            continue
        rows, changed = [], False
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("deliver") == "morning" and not e.get("delivered") and e.get("message"):
                out.append(e["message"])
                if mark:
                    e.update(delivered=True, delivered_at=datetime.now(cc.tz()).isoformat(),
                             delivered_via="hridaya-fallback")
                    changed = True
            rows.append(e)
        if changed:
            f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return out


# --- scadenze --------------------------------------------------------------------------

def deadlines(day: str, horizon_days: int = 2) -> list[dict]:
    """Voci non fatte di data/scadenze.json entro horizon_days (e quelle scadute)."""
    items = (_json(_root() / "data" / "scadenze.json") or {}).get("items") or []
    today = date.fromisoformat(day)
    out = []
    for it in items:
        if it.get("done") or not it.get("due"):
            continue
        try:
            left = (date.fromisoformat(it["due"]) - today).days
        except ValueError:
            continue
        if left <= horizon_days:
            out.append({**it, "days_left": left})
    return sorted(out, key=lambda it: it["days_left"])


def is_blood_draw(it: dict) -> bool:
    return it.get("kind") in ("prelievo", "esami") or bool(
        PRELIEVO.search(f"{it.get('id', '')} {it.get('title', '')}"))


def format_deadlines(items: list[dict]) -> list[str]:
    if not items:
        return []
    lines = ["📌 Scadenze (48 h)"]
    for it in items:
        due = date.fromisoformat(it["due"])
        left = it["days_left"]
        when = "SCADUTA" if left < 0 else "oggi" if left == 0 else "domani" if left == 1 else f"tra {left} gg"
        lines.append(f"• {it['title']} — {GIORNI[due.weekday()]} {due:%d/%m} ({when})")
    return lines


# --- sera ------------------------------------------------------------------------------

def therapy_reminders(day: str) -> list[str]:
    """Promemoria serali già concordati col medico (config/insights.json → therapy_nudge).
    Stessa regola di circadian_plan.therapy_reminders (DreamAgent): giorni nominati."""
    cfg = ((_json(_root() / "config" / "insights.json") or {}).get("therapy_nudge")) or {}
    if not cfg.get("enabled"):
        return []
    wd = GIORNI[date.fromisoformat(day).weekday()]
    return [i["text"] for i in cfg.get("items") or [] if i.get("text") and wd in (i.get("days") or [])]


def evening_text(day: str, active: bool = False) -> str:
    r = cc.rhythm()
    lines = [f"{cc_auto(active)} · 🌙 Ora di letto: {r['bedtime']}"
             + (f" (sveglia {r['target_wake']})" if r.get("target_wake") else "")]
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    draws = [it for it in deadlines(day, 1) if it["due"] == tomorrow and is_blood_draw(it)]
    for it in draws:
        prep = it.get("prep") or "di solito digiuno dalla sera; niente allenamento intenso prima"
        lines.append(f"🩸 Domani: {it['title']} — {prep}.")
    rem = therapy_reminders(day)
    if rem:
        lines += [""] + rem
    return "\n".join(lines)


def wake_text(day: str, mark: bool = True, active: bool = False) -> str:
    lines = [f"{cc_auto(active)} · buongiorno"] + night_lines(day)
    ev = morning_events(day, mark=mark)
    if ev:
        lines += [""] + ev
    dl = format_deadlines(deadlines(day))
    if dl:
        lines += [""] + dl
    return "\n".join(lines)


def cc_auto(active: bool = False) -> str:
    """«non attivo» solo se la sessione davvero non c'è (con la sessione accesa ma muta: solo automatico)."""
    return "🤖 automatico" if active else "🤖 automatico (Hṛdaya non è attivo)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fallback deterministici di Hṛdaya")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--wake", action="store_true", help="messaggio dopo l'alzata (default)")
    g.add_argument("--evening", action="store_true")
    ap.add_argument("--date", default=None)
    ap.add_argument("--print", action="store_true", help="stampa soltanto, non invia")
    ap.add_argument("--trigger", default="manual", help="compatibilità col vecchio launchd (ignorato)")
    a = ap.parse_args()
    day = a.date or datetime.now(cc.tz()).strftime("%Y-%m-%d")
    kind = "evening" if a.evening else "wake"
    if a.print:
        print(evening_text(day) if a.evening else wake_text(day, mark=False))
        return 0
    import push_gate
    text = evening_text(day) if a.evening else wake_text(day)
    print(json.dumps(push_gate.deliver(text, kind, push_gate.TelegramSender(), source="fallback-cli"),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
