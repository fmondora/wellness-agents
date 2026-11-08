#!/usr/bin/env python3.12
"""Bottoni «▶️ Inizia» / «⏹ Fine» sotto una pratica (meditazione, dharana, vocale guidato).

La persona dice quando comincia e quando finisce; il bot lo registra da solo (senza la sessione) e,
mezz'ora dopo la fine (la discesa si misura DOPO la seduta), mette in coda l'evento di sistema
`practice_done` con la finestra: la sessione la legge sulla FC al minuto (plugin health,
`meditation_detect.py INIZIO FINE --date --note`).

  ▶️ Inizia  → registra l'inizio, il bottone diventa ⏹ Fine
  ⏹ Fine     → registra la fine, la tastiera diventa «✓ 18:30–19:01 · 31′» (inerte)

Stato in data/hridaya/practices.json:
  {"<pid>": {"title", "kind", "created_at", "started_at"?, "ended_at"?, "seen": [tap_id...]}}
callback_data: "pr:<pid>:start" | "pr:<pid>:end" | "pr:noop".
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import channel_config as cc
import telegram_queue as tq

KEEP_DAYS = 60
MAX_OPEN_H = 4          # un «Inizia» senza «Fine» per più di 4 ore: la seduta non si chiude più
MAX_SEEN = 20
READ_AFTER_MIN = 30     # l'evento parte dopo: servono i minuti successivi alla seduta


def path():
    return cc.data_root().resolve() / "data" / "hridaya" / "practices.json"


def _load() -> dict[str, dict]:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st: dict[str, dict]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    st = {k: v for k, v in st.items() if v.get("created_at", "") >= cutoff}
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def start_markup(pid: str) -> dict:
    return {"inline_keyboard": [[{"text": "▶️ Inizia", "callback_data": f"pr:{pid}:start"}]]}


def end_markup(pid: str) -> dict:
    return {"inline_keyboard": [[{"text": "⏹ Fine", "callback_data": f"pr:{pid}:end"}]]}


def done_markup(text: str) -> dict:
    return {"inline_keyboard": [[{"text": text[:64], "callback_data": "pr:noop"}]]}


def create(title: str, kind: str = "meditation", pid: str | None = None) -> tuple[str, dict]:
    """Registra una pratica → (pid, tastiera con «Inizia»). Stesso pid due volte = stessa pratica."""
    pid = pid if pid and re.fullmatch(r"[0-9a-f]{8,16}", pid) else uuid.uuid4().hex[:12]
    with tq.locked():
        st = _load()
        st.setdefault(pid, {"title": (title or "")[:120], "kind": kind,
                            "created_at": datetime.now(timezone.utc).isoformat()})
        _save(st)
    return pid, start_markup(pid)


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(cc.tz())


def summary(p: dict) -> str:
    a, b = _local(p["started_at"]), _local(p["ended_at"])
    mins = max(1, round((b - a).total_seconds() / 60))
    return f"✓ {a:%H:%M}–{b:%H:%M} · {mins}′"


def tap(data: str, tap_id: str | None = None, now: datetime | None = None) -> dict:
    """→ {"action": "noop"|"stale"|"started"|"ended", "toast", "markup"?, "practice"?}"""
    parts = (data or "").split(":")
    if parts[:1] != ["pr"] or parts[1:2] == ["noop"]:
        return {"action": "noop", "toast": ""}
    if len(parts) != 3 or parts[2] not in ("start", "end"):
        return {"action": "stale", "toast": "Bottone non valido"}
    pid, arg = parts[1], parts[2]
    now = now or datetime.now(timezone.utc)
    with tq.locked():
        st = _load()
        p = st.get(pid)
        if not p:
            return {"action": "stale", "toast": "Questa pratica è scaduta", "markup": {"inline_keyboard": []}}
        if tap_id and tap_id in (p.get("seen") or []):
            return {"action": "noop", "toast": ""}
        if tap_id:
            p["seen"] = (p.get("seen") or [])[-(MAX_SEEN - 1):] + [tap_id]
        if p.get("ended_at"):
            st[pid] = p
            _save(st)
            return {"action": "stale", "toast": "Già registrata", "markup": done_markup(summary(p))}
        if arg == "start":
            if not p.get("started_at"):
                p["started_at"] = now.isoformat()
            st[pid] = p
            _save(st)
            return {"action": "started", "toast": "Buona pratica 🙏 Tocca «Fine» quando hai finito",
                    "markup": end_markup(pid), "practice": {"id": pid, **p}}
        if not p.get("started_at"):
            st[pid] = p
            _save(st)
            return {"action": "stale", "toast": "Prima tocca «Inizia»", "markup": start_markup(pid)}
        if now - datetime.fromisoformat(p["started_at"]) > timedelta(hours=MAX_OPEN_H):
            p.pop("started_at")
            st[pid] = p
            _save(st)
            return {"action": "stale", "toast": "L'inizio è di ore fa: tocca di nuovo «Inizia»",
                    "markup": start_markup(pid)}
        p["ended_at"] = now.isoformat()
        st[pid] = p
        _save(st)
    return {"action": "ended", "toast": "Registrata 🙏", "markup": done_markup(summary(p)),
            "practice": {"id": pid, **{k: v for k, v in p.items() if k != "seen"}}}


def due(now: datetime | None = None) -> list[dict]:
    """Pratiche finite da almeno READ_AFTER_MIN minuti e non ancora annunciate: le segna annunciate."""
    now = now or datetime.now(timezone.utc)
    out = []
    with tq.locked():
        st = _load()
        for pid, p in st.items():
            if p.get("ended_at") and not p.get("notified") and \
                    now - datetime.fromisoformat(p["ended_at"]) >= timedelta(minutes=READ_AFTER_MIN):
                p["notified"] = now.isoformat()
                out.append({"id": pid, **{k: v for k, v in p.items() if k != "seen"}})
        if out:
            _save(st)
    return out


def event(p: dict) -> tuple[str, dict]:
    """Testo e dati dell'evento `practice_done` per la sessione."""
    a, b = _local(p["started_at"]), _local(p["ended_at"])
    data: dict[str, Any] = {"id": p["id"], "title": p.get("title", ""), "kind": p.get("kind", ""),
                            "date": a.date().isoformat(), "start": f"{a:%H:%M}", "end": f"{b:%H:%M}",
                            "minutes": max(1, round((b - a).total_seconds() / 60))}
    text = (f"Pratica fatta: «{data['title']}» dalle {data['start']} alle {data['end']} ({data['minutes']}′). "
            f"Leggi la finestra sulla FC al minuto (health: meditation_detect.py {data['start']} {data['end']} "
            f"--date {data['date']}).")
    return text, data
