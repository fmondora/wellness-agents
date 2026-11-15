#!/usr/bin/env python3.12
"""Il diario di oggi in ordine, per /diario (anche /journal e /log): notte, movimento, pratica,
corpo, energia, cose da registrare, quello che ha scritto lui. Deterministico, senza LLM.

Sotto, i bottoni: «✍️ Aggiorna il diario» (la sessione fa le domande, una alla volta) e, se il
registro ha una domanda da fare adesso, «📋 Registra». Se oggi non ha ancora registrato niente di
suo, lo dice. callback_data: "dj:aggiorna" | "dj:registra".

    journal.py [--date YYYY-MM-DD]      stampa il testo (HTML di Telegram)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
UPDATE_TEXT = "📓 Aggiorniamo il diario di oggi"     # il messaggio che il bottone mette in coda
MAX_ROWS = 6                # righe per sezione: il resto è «… e altre n»
MAX_CHARS = 3800            # un messaggio solo: i bottoni stanno sotto tutto il diario
MAX_WRITTEN = 4
# righe del diario che non sono parole sue (comandi, tocchi, eventi, righe scritte dalla sessione)
_NOISE = re.compile(r"^(/\w+|\[bottone\]|\[pratica\]|\[diario|\[log\]|\[allenamento\]|\[red flag\]|Metriche:)",
                    re.I)
_MSG = re.compile(r"^\[Telegram (\d{2}:\d{2})\] (?:\[coda ([0-9a-f]+)\] )?(.*)$")
_PREFER = ("score", "reported", "note", "value", "nota", "reading", "bristol", "livello", "tipo")


def _e(s: Any) -> str:
    return html.escape(str(s), quote=False)


def _d(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _blank(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _short(v: Any, n: int = 90) -> str:
    if isinstance(v, dict):
        for k in _PREFER:
            if not _blank(v.get(k)):
                return _short(v[k], n)
        v = ", ".join(f"{k} {x}" for k, x in v.items() if isinstance(x, (str, int, float)))
    elif isinstance(v, list):
        v = ", ".join(_short(x, n) for x in v if not _blank(x))
    s = " ".join(str(v).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _json(p: Path) -> dict:
    try:
        return _d(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _night(day: str) -> list[str]:
    try:
        import morning_message as mm
        return [_e(x.strip()) for x in mm.night_lines(day)]
    except Exception:  # noqa: BLE001
        return []


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("value") or v.get("total")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v else None


def _movement(day: str, log: dict) -> list[str]:
    root = cc.data_root() / "data"
    fit = _json(root / "fitbit" / f"{day}.json") or _d(log.get("fitbit"))
    out = []
    steps, azm = _num(fit.get("steps")), _num(fit.get("azm"))
    if steps:
        out.append(f"{int(steps):,} passi".replace(",", "."))
    if azm:
        out.append(f"{int(azm)} minuti attivi")
    if (root / "coach-longevita" / "daily" / f"{day}.session.json").exists():
        out.append("seduta registrata col player")
    rows = [" · ".join(out)] if out else []
    sauna = _d(_d(log.get("movement")).get("sauna"))
    if sauna.get("done") and sauna.get("rounds"):
        n = sauna["rounds"]
        rows.append(_e(f"sauna: {'un passaggio' if n == 1 else f'{n} passaggi'} nel calore, {sauna.get('heat_min', '?')} minuti"
                       + (f", riposo {sauna['rest_min']} minuti" if sauna.get("rest_min") else "")))
    return rows


def _practice(log: dict) -> list[str]:
    out = []
    med = _d(_d(log.get("morning")).get("meditation"))
    if med.get("start"):
        what = f" «{_e(med['practice'])}»" if med.get("practice") else ""
        out.append(f"meditazione{what} {_e(med['start'])}–{_e(med.get('end', '?'))}"
                   + (f" ({_e(med['minutes'])}′)" if med.get("minutes") else ""))
    note = _d(log.get("practice")).get("night_note")
    if note:
        out.append(_e(_short(note)))
    ps = log.get("practices")
    for p in ps if isinstance(ps, list) else []:
        if not isinstance(p, dict):
            continue
        name = " ".join(str(p[k]) for k in ("type", "style") if p.get(k)).replace("_", " ") or str(p.get("title") or "")
        when = "–".join(str(p[k]) for k in ("start", "end") if p.get(k))
        row = " ".join(x for x in (name, when, f"con {p['with']}" if p.get("with") else "") if x)
        if row:
            out.append(_e(row))
    return out


def _body(log: dict) -> list[str]:
    out = []
    for k, v in _d(log.get("symptoms")).items():
        if not _blank(v):
            out.append(f"{_e(str(k).replace('_', ' '))}: {_e(_short(v, 70))}")
    if not _blank(log.get("bowel")):
        b = log["bowel"]
        txt = ", ".join(_short(x, 40) for x in b.values() if not _blank(x)) if isinstance(b, dict) else _short(b, 70)
        out.append(f"intestino: {_e(_short(txt, 90))}")
    tin = _d(log.get("morning")).get("tinnitus")
    if not _blank(tin):
        out.append(f"acufeni al mattino: {_e(_short(tin, 40))}")
    return out


def _energy(log: dict) -> list[str]:
    out = []
    for src, lab in ((log.get("energy"), "energia"), (log.get("mood"), "umore")):
        if isinstance(src, dict):
            out += [f"{lab}: {_e(_short(v, 70))}" for v in src.values() if not _blank(v)]
        elif not _blank(src):
            out.append(f"{lab}: {_e(_short(src, 70))}")
    ev = _d(log.get("evening"))
    if not _blank(ev.get("energy")):
        out.append(f"sera: {_e(_short(ev['energy'], 70))}")
    m = _d(log.get("morning"))
    if m.get("hrv") or m.get("heart_rate"):
        out.append(f"HRV {_e(m.get('hrv', '—'))} · FC {_e(m.get('heart_rate', '—'))} (misura del mattino)")
    return out


def written(log: dict) -> list[str]:
    """Le sue parole di oggi (dai messaggi): la prima riga per messaggio (quella del bot, il testo
    originale: le riscritture della sessione sullo stesso id non contano), senza comandi né tocchi."""
    notes = log.get("notes")
    if isinstance(notes, list):
        notes = "\n".join(map(str, notes))
    out, seen_ids, seen = [], set(), set()
    for ln in str(notes or "").splitlines():
        m = _MSG.match(ln.strip())
        if not m:
            continue
        hhmm, cid, text = m.group(1), m.group(2), m.group(3).strip()
        if cid:
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
        if not text or _NOISE.match(text) or len(text) < 4:
            continue
        key = re.sub(r"\W+", "", text.lower())[:30]       # lo stesso messaggio corretto e rimandato
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{hhmm} {_e(_short(text, 110))}")
    return out[-MAX_WRITTEN:]


def has_own_entries(log: dict, day: str) -> bool:
    """Oggi ha registrato qualcosa di suo (a parole o coi bottoni), non solo dati del wearable."""
    if any(not _blank(log.get(k)) for k in ("energy", "mood", "symptoms", "evening", "bowel", "practices", "practice")):
        return True
    m = _d(log.get("morning"))
    if any(not _blank(m.get(k)) for k in ("tinnitus", "meditation")):
        return True
    try:
        import log_plan as lp
        if lp.answered_today(day):
            return True
    except Exception:  # noqa: BLE001
        pass
    return bool(written(log))


def text(day: str | None = None, now: datetime | None = None) -> tuple[str, dict]:
    """→ (testo HTML, info: {"own": bool, "missing": domande che il registro farebbe adesso})."""
    now = now or datetime.now(cc.tz())
    day = day or now.date().isoformat()
    log = _json(cc.data_root() / "data" / "logs" / f"{day}.json")
    d = date.fromisoformat(day)
    lines = [f"📓 <b>Diario di {GIORNI[d.weekday()]} {d.day}/{d.month}</b>"]

    def section(icon: str, title: str, rows: list[str]) -> None:
        rows = [r for r in rows if r.strip()]
        if not rows:
            return
        extra = len(rows) - MAX_ROWS
        if extra > 0:
            rows = rows[:MAX_ROWS] + [f"… e altre {extra}"]
        lines.append(f"\n{icon} <b>{title}</b>\n" + "\n".join(f"   {r}" for r in rows))

    section("🌙", "Notte", _night(day))
    section("🚶", "Movimento", _movement(day, log))
    section("🧘", "Pratica", _practice(log))
    section("🩺", "Corpo", _body(log))
    section("⚡", "Energia e umore", _energy(log))
    plan, missing = [], 0
    try:
        import log_plan as lp
        plan = lp.summary(day)
        if day == now.date().isoformat():
            missing = lp.open_count(day, lp.ask_scope(now))
    except Exception:  # noqa: BLE001
        pass
    section("📋", "Da registrare", [_e(x) for x in plan])
    section("✍️", "Cosa mi hai scritto oggi", written(log))
    own = has_own_entries(log, day)
    if not own:
        lines.append("\nOggi non hai ancora registrato niente di tuo. Se vuoi, lo facciamo adesso: due domande.")
    out = "\n".join(lines)
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS].rsplit("\n", 1)[0] + "\n…"
    return out, {"own": own, "missing": missing}


def markup(info: dict) -> dict:
    row = [{"text": "✍️ Aggiorna il diario" if info.get("own") else "✍️ Scrivi il diario",
            "callback_data": "dj:aggiorna"}]
    if info.get("missing"):
        row.append({"text": f"📋 Registra ({info['missing']})", "callback_data": "dj:registra"})
    return {"inline_keyboard": [row]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    print(text(a.date)[0])
