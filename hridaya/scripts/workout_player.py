#!/usr/bin/env python3.12
"""Workout player (Telegram Mini App) — il lato canale, di Hṛdaya.

Il player (pagina, motore, voce) è di Coach Longevità; il contratto fra i due è il
formato `player.json` / `session.json` (coach-longevita/apps/workout-player/README.md).
Qui, nel canale:
- valida il workout JSON del coach e costruisce l'URL della Mini App (#w=… nel fragment);
- manda il bottone "▶️ Avvia allenamento" come reply keyboard (sendData funziona solo così);
- decodifica il log che torna con message.web_app_data e lo salva come
  data/coach-longevita/daily/YYYY-MM-DD.session.json (unendo continuazioni e reinvii);
- sceglie l'ultimo player.json per /allenamento e pubblica il menu comandi del bot.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tg_transport import call as tg_call  # noqa: E402

ROOT = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
DAILY = ROOT / "data" / "coach-longevita" / "daily"
TZ = ZoneInfo(os.environ.get("WELLNESS_TZ", "Europe/Rome"))
BUTTON_TEXT = "▶️ Avvia allenamento"

EVENTS = ["start", "step", "pause", "resume", "skip", "done", "round", "stop", "end"]
KINDS = {"p": "prep", "w": "work", "r": "rest"}
TYPES = {"timed", "sets", "emom", "interval", "amrap", "fortime"}
MAX_PLAIN_URL = 2048  # oltre, il fragment va compresso (deflate-raw, iOS ≥ 16.4)


# --- workout → URL -----------------------------------------------------------

def validate_workout(w: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(w, dict):
        return ["il workout deve essere un oggetto"]
    if not isinstance(w.get("blocks"), list) or not w["blocks"]:
        return ["blocks mancante o vuoto"]
    for i, b in enumerate(w["blocks"], 1):
        p = f"blocco {i}"
        t = b.get("type")
        if t not in TYPES:
            errs.append(f"{p}: type {t!r} non tra {sorted(TYPES)}")
        if not b.get("name"):
            errs.append(f"{p}: name mancante")
        exs = b.get("exercises")
        if not isinstance(exs, list) or not exs:
            errs.append(f"{p}: exercises vuoto")
            continue
        for j, ex in enumerate(exs, 1):
            if not isinstance(ex, dict) or not ex.get("name"):
                errs.append(f"{p} esercizio {j}: name mancante")
            elif ex.get("img") is not None and not re.fullmatch(r"[a-z0-9-]+", str(ex["img"])):
                errs.append(f"{p} esercizio {j}: img deve essere uno slug (a-z, 0-9, -)")
        need = {"emom": ["minutes"], "interval": ["work_s"], "amrap": ["duration_s"]}.get(t, [])
        for k in need:
            if not isinstance(b.get(k), (int, float)) or b[k] <= 0:
                errs.append(f"{p}: {k} deve essere > 0")
        if t == "timed" and len(exs) == 1 and not (exs[0].get("time_s") or b.get("duration_s")):
            errs.append(f"{p}: timed con un esercizio vuole time_s o duration_s")
    return errs


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def encode_fragment(w: dict) -> str:
    raw = json.dumps(w, ensure_ascii=False, separators=(",", ":")).encode()
    plain = "w=" + _b64url(raw)
    if len(plain) <= MAX_PLAIN_URL - 100:
        return plain
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return "z=" + _b64url(c.compress(raw) + c.flush())


def build_url(base: str, w: dict) -> str:
    return base.split("#")[0] + "#" + encode_fragment(w)


def keyboard(url: str) -> dict:
    return {"keyboard": [[{"text": BUTTON_TEXT, "web_app": {"url": url}}]],
            "resize_keyboard": True, "one_time_keyboard": False}


def send_player_button(token: str, chat_id: int | str, w: dict, base_url: str,
                       call: Callable[..., dict] = tg_call, text: str | None = None) -> dict:
    url = build_url(base_url, w)
    text = text or f"🏋️ {w.get('title') or 'Allenamento'}\nTocca il bottone qui sotto per aprire il timer."
    return call(token, "sendMessage", chat_id=chat_id, text=text, reply_markup=keyboard(url))


# --- web_app_data → session.json ---------------------------------------------

def _iso(ms: int | float) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).isoformat(timespec="seconds")


def decode_web_app_data(data: str, received: datetime | None = None) -> dict:
    o = json.loads(data)
    if o.get("v") != 1:
        raise ValueError(f"versione log sconosciuta: {o.get('v')!r}")
    t0 = int(o["t0"])
    blocks = o.get("B") or []
    steps = {}
    for row in o.get("S") or []:
        i, b, k = row[0], row[1], row[2]
        steps[i] = {"i": i, "block": b, "block_name": blocks[b] if b < len(blocks) else None,
                    "kind": KINDS.get(k, k), "label": row[3] if len(row) > 3 else None}
    events = []
    for a in o.get("E") or []:
        st = steps.get(a[2], {})
        ev = {"t": _iso(t0 + a[0] * 1000), "e": EVENTS[a[1]], "block": st.get("block"),
              "block_name": st.get("block_name"), "step": a[2], "kind": st.get("kind"),
              "label": st.get("label")}
        flags = a[3] if len(a) > 3 else 0
        if flags & 1:
            ev["auto"] = True
        if flags & 2:
            ev["reopen"] = True  # ripresa dopo che l'app era stata chiusa
        if flags & 4:
            ev["cont"] = True    # continuazione dopo uno stop
        events.append(ev)
    if not events:
        raise ValueError("log senza eventi")
    received_at = (received or datetime.now(TZ)).isoformat(timespec="seconds")
    cont = int(o.get("cont") or 0)
    debrief = None
    q, nt = o.get("q"), o.get("nt")
    if isinstance(q, dict) or nt:
        answers = {str(k)[:40]: str(v)[:40] for k, v in (q or {}).items()} if isinstance(q, dict) else {}
        debrief = {"answers": answers, "note": str(nt or "")[:280], "received_at": received_at}
    return {
        "debrief": debrief,
        "workout_date": o.get("d"),
        "title": o.get("n"),
        "status": o.get("st"),
        "demo": bool(o.get("demo")),
        "started_at": events[0]["t"],
        "ended_at": events[-1]["t"],
        "received_at": received_at,
        "truncated_events": o.get("tr", 0),
        # t0 della seduta (per riconoscere continuazioni e reinvii); cont = t0 della seduta originale
        "t0_ms": cont or t0,
        "is_continuation": bool(cont),
        "blocks": blocks,
        "steps": [steps[i] for i in sorted(steps)],
        "events": events,
        "segments": [{"received_at": received_at, "from": events[0]["t"], "to": events[-1]["t"],
                      "events": len(events), "status": o.get("st"), "continuation": bool(cont), "raw": data}],
        "raw": data,
    }


def _t(ev: dict) -> datetime:
    return datetime.fromisoformat(ev["t"])


def merge_sessions(old: dict, new: dict) -> dict:
    """Unisce a una seduta salvata la sua continuazione (o un reinvio): eventi in ordine di
    tempo senza doppioni, passi uniti, un segmento in più."""
    seen = {(e["t"], e["e"], e["step"]) for e in old["events"]}
    events = old["events"] + [e for e in new["events"] if (e["t"], e["e"], e["step"]) not in seen]
    events.sort(key=_t)
    steps = {st["i"]: st for st in old.get("steps", [])}
    for st in new.get("steps", []):
        steps.setdefault(st["i"], st)
    out = dict(old)
    out.update(events=events, steps=[steps[i] for i in sorted(steps)],
               started_at=events[0]["t"], ended_at=events[-1]["t"],
               status=events[-1]["e"] if events[-1]["e"] in ("stop", "end") else new.get("status"),
               segments=old.get("segments", []) + new.get("segments", []),
               truncated_events=old.get("truncated_events", 0) + new.get("truncated_events", 0))
    if new.get("debrief"):  # l'ultimo debrief inviato vince (si risponde a fine seduta)
        out["debrief"] = new["debrief"]
    return out


def find_session(t0_ms: int, daily: Path = DAILY) -> Path | None:
    day = datetime.fromtimestamp(t0_ms / 1000, TZ).strftime("%Y-%m-%d")
    for f in sorted(daily.glob(f"{day}*.session.json")):
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("t0_ms") == t0_ms:
                return f
        except (OSError, json.JSONDecodeError):
            continue
    return None


def store_session(session: dict, daily: Path = DAILY) -> tuple[Path, dict, bool]:
    """Salva la seduta; se è la continuazione (o il reinvio) di una già salvata la unisce.
    Torna (file, seduta salvata, unita?)."""
    if session.get("t0_ms"):
        f = find_session(session["t0_ms"], daily)
        if f:
            merged = merge_sessions(json.loads(f.read_text(encoding="utf-8")), session)
            f.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            return f, merged, True
    return save_session(session, daily), session, False


def save_session(session: dict, daily: Path = DAILY) -> Path:
    day = session["started_at"][:10]
    if session.get("is_continuation") and session.get("t0_ms"):   # originale non trovato: data dell'originale
        day = datetime.fromtimestamp(session["t0_ms"] / 1000, TZ).strftime("%Y-%m-%d")
    ext = ".demo.session.json" if session.get("demo") else ".session.json"
    daily.mkdir(parents=True, exist_ok=True)
    path = daily / f"{day}{ext}"
    n = 2
    while path.exists():
        path = daily / f"{day}-{n}{ext}"
        n += 1
    path.write_text(json.dumps(session, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def reply_text(session: dict) -> str:
    a, b = session["started_at"][11:16], session["ended_at"][11:16]
    tag = "" if session.get("status") == "end" else " — fermata prima della fine"
    if session.get("demo"):
        tag += " (demo)"
    return f"✓ Seduta registrata ({a}–{b}, {len(session['events'])} eventi){tag}"


def handle_web_app_data(token: str, chat_id: int, data: str, daily: Path = DAILY,
                        call: Callable[..., dict] = tg_call) -> Path | None:
    try:
        session = decode_web_app_data(data)
        path, saved, merged = store_session(session, daily)
        text = reply_text(saved)
        if merged:
            new = len(session["events"])
            text = (f"✓ Continuazione registrata, unita alla seduta delle {saved['started_at'][11:16]} "
                    f"({saved['started_at'][11:16]}–{saved['ended_at'][11:16]}, {len(saved['events'])} eventi, "
                    f"{new} nuovi, {len(saved['segments'])} parti)")
    except Exception as e:  # noqa: BLE001 — log illeggibile: salvo il grezzo e lo dico
        daily.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(TZ).strftime("%Y-%m-%d-%H%M%S")
        path = daily / f"{stamp}.session-raw.txt"
        path.write_text(data, encoding="utf-8")
        text = f"⚠️ Log della seduta illeggibile ({e}); salvato grezzo in {path.name}"
    call(token, "sendMessage", chat_id=chat_id, text=text, reply_markup={"remove_keyboard": True})
    return path


def latest_player(daily: Path = DAILY, today: str | None = None) -> Path | None:
    """L'ultimo YYYY-MM-DD.player.json con data <= oggi; i demo solo se non c'è altro."""
    today = today or datetime.now(TZ).strftime("%Y-%m-%d")
    real, demo = [], []
    for f in daily.glob("????-??-??.player.json"):
        day = f.name[:10]
        if day > today:
            continue
        try:
            is_demo = bool(json.loads(f.read_text(encoding="utf-8")).get("demo"))
        except (OSError, json.JSONDecodeError):
            continue
        (demo if is_demo else real).append((day, f))
    pick = real or demo
    return max(pick)[1] if pick else None


BOT_COMMANDS = [
    {"command": "allenamento", "description": "Riapri l'ultimo allenamento"},
    {"command": "log", "description": "Riepilogo del diario di oggi"},
    {"command": "nota", "description": "Annota nel diario: /nota testo"},
    {"command": "sonno", "description": "Analisi della notte"},
    {"command": "help", "description": "Cosa so fare"},
]


def set_bot_commands(token: str, call: Callable[..., dict] = tg_call) -> None:
    """Menu comandi della chat privata (idempotente: setMyCommands sovrascrive)."""
    call(token, "setMyCommands", commands=BOT_COMMANDS, scope={"type": "all_private_chats"})
