#!/usr/bin/env python3.12
"""Il rito (Telegram Mini App del Maestro di sauna) — il lato canale, di Hṛdaya.

La pagina, il motore e i suoni sono di `maestro-sauna`; il contratto fra i due sono i file
`rito.json` / `session.json` (maestro-sauna/apps/rito/README.md). Qui, nel canale:
- fa passare la partitura dalla soglia del Maestro (`rito_guard.check`: forma, tetti, giorno) e
  costruisce l'URL della Mini App (#r=… nel fragment: non arriva al server della pagina);
- manda il bottone «♨️ Apri il rito» come reply keyboard (sendData funziona solo così) e ricorda
  che oggi è stato mandato (una riapertura a metà rito non rifà i conti dell'ora);
- riconosce il ritorno (`web_app_data` con k = "rito") e lo salva in
  data/sauna/sessions/YYYY-MM-DD.session.json con i tempi veri di ogni momento: quelli che il
  motore ha calcolato (`A`), o, se mancano, il log rigiocato (stessa logica di engine.js);
- scrive la seduta nel diario del suo giorno (`movement.sauna`, senza cancellare ciò che c'era);
- sceglie il rito di oggi per /sauna.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import math
import os
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tg_transport import call as tg_call

BUTTON_TEXT = "♨️ Apri il rito"
CLOSE_TEXT = "⏹ Chiudi il rito"
EVENTS = ["start", "enter", "tap", "auto", "skip", "pause", "resume", "undo", "stop", "end", "begin"]
MAX_PLAIN_URL = 2048   # oltre, il fragment va compresso (deflate-raw, iOS ≥ 16.4)
MAX_URL = 6000         # oltre, la partitura è troppo lunga per un bottone
PAGE_IGNORES = ("threshold",)   # campi della partitura che la pagina non legge: non viaggiano nel bottone


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("WELLNESS_TZ", "Europe/Rome"))


def _root(root: Path | None = None) -> Path:
    return Path(root or os.environ.get("WELLNESS_DATA") or Path.cwd())


def riti_dir(root: Path | None = None) -> Path:
    return _root(root) / "data" / "sauna" / "riti"


def sessions_dir(root: Path | None = None) -> Path:
    return _root(root) / "data" / "sauna" / "sessions"


def today(now: datetime | None = None) -> str:
    return (now or datetime.now(_tz())).strftime("%Y-%m-%d")


# --- soglia --------------------------------------------------------------------------

_GUARD: dict = {}


def installed() -> bool:
    from _plugins import plugin_scripts
    return plugin_scripts("maestro-sauna") is not None


def _guard_module():
    """`rito_guard` del plugin maestro-sauna, ricaricato se il plugin è stato aggiornato (il bot resta
    acceso per giorni: una soglia più stretta deve valere subito)."""
    from _plugins import plugin_scripts
    d = plugin_scripts("maestro-sauna")
    if d is None:
        return None
    f = d / "rito_guard.py"
    key = (str(f), f.stat().st_mtime)
    if _GUARD.get("key") != key:
        spec = importlib.util.spec_from_file_location("rito_guard_live", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GUARD.update(key=key, mod=mod)
    return _GUARD["mod"]


def guard(r: dict, root: Path | None = None, reopen: bool = False) -> list[str]:
    """Perché il rito non può partire. Senza il plugin del Maestro non parte: la soglia è sua."""
    try:
        g = _guard_module()
    except Exception as e:  # noqa: BLE001 — una soglia che non si carica resta chiusa
        return [f"la soglia del rito non è disponibile ({e.__class__.__name__}: {e}): resta chiusa"]
    if g is None:
        return ["il Maestro di sauna non è installato (plugin maestro-sauna): niente soglia, niente rito"]
    try:
        return g.check(r, root=_root(root), reopen=reopen)
    except Exception as e:  # noqa: BLE001
        return [f"la soglia del rito ha dato errore ({e.__class__.__name__}: {e}): resta chiusa"]


def sent_path(root: Path | None = None) -> Path:
    return _root(root) / "data" / "sauna" / "sent.json"


def mark_sent(root: Path | None = None, day: str | None = None) -> None:
    """Oggi il bottone di questo rito è partito (dopo la soglia piena)."""
    p = sent_path(root)
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st = {k: v for k, v in (st if isinstance(st, dict) else {}).items() if k >= (day or today())}
    st.setdefault(day or today(), datetime.now(_tz()).isoformat(timespec="seconds"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1) + "\n", encoding="utf-8")


def was_sent(root: Path | None = None, day: str | None = None) -> bool:
    try:
        return (day or today()) in json.loads(sent_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False


def closed_session(root: Path | None = None, day: str | None = None) -> dict | None:
    """La seduta di oggi già chiusa (rito compiuto o interrotto e inviato), se c'è."""
    day = day or today()
    for f in sorted(sessions_dir(root).glob(f"{day}*.session.json")):
        if f.name.endswith(".demo.session.json"):
            continue
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(s, dict) and s.get("status") in ("end", "stop"):
            return s
    return None


# --- URL e bottone -------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def encode_fragment(r: dict) -> str:
    r = {k: v for k, v in r.items() if k not in PAGE_IGNORES}     # le note della soglia restano nel repo dati
    raw = json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode()
    plain = "r=" + _b64url(raw)
    if len(plain) <= MAX_PLAIN_URL - 100:
        return plain
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return "z=" + _b64url(c.compress(raw) + c.flush())


def build_url(base: str, r: dict) -> str:
    url = base.split("#")[0] + "#" + encode_fragment(r)
    if len(url) > MAX_URL:
        raise ValueError(f"partitura troppo lunga per il bottone ({len(url)} caratteri, il limite è {MAX_URL}): "
                         "il Maestro accorci i testi")
    return url


def keyboard(url: str) -> dict:
    return {"keyboard": [[{"text": BUTTON_TEXT, "web_app": {"url": url}}], [{"text": CLOSE_TEXT}]],
            "resize_keyboard": True, "one_time_keyboard": False}


def send_rito_button(token: str, chat_id: int | str, r: dict, base_url: str, call: Callable[..., dict] = tg_call,
                     text: str | None = None, parse_mode: str | None = None) -> dict:
    text = text or f"♨️ {r.get('title') or 'Rito'}\nQuando sei pronto, tocca il bottone qui sotto."
    if r.get("demo"):
        text = "Prova a secco: non conta come sauna e non entra nel diario.\n\n" + text
    return call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode=parse_mode,
                reply_markup=keyboard(build_url(base_url, r)))


def latest_rito(root: Path | None = None, day: str | None = None) -> Path | None:
    """La partitura di oggi (i riti non si riaprono nei giorni dopo: li riscrive il Maestro)."""
    f = riti_dir(root) / f"{day or today()}.rito.json"
    return f if f.exists() else None


# --- ritorno → session.json -----------------------------------------------------------

def is_rito_data(data: str) -> bool:
    try:
        o = json.loads(data)
    except (ValueError, TypeError, RecursionError):
        return False
    return isinstance(o, dict) and o.get("k") == "rito"


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, _tz()).isoformat(timespec="seconds")


def _round(x: float) -> int:
    """Come Math.round: le mezze vanno in su (round() di Python le manda al pari)."""
    return int(math.floor(x + 0.5))


def _replay(spec: list[dict], raw: list, t0: int) -> tuple[list[dict], list[dict], str | None]:
    """Rigioca gli eventi come engine.js (apply + summary) → (momenti, eventi leggibili, status)."""
    recs: list[dict] = []
    events: list[dict] = []
    cur, m_start, paused_at, prev, status = None, 0.0, 0.0, None, None

    def close(t: float, how: str) -> None:
        if recs and recs[-1].get("end") is None:
            recs[-1]["end"], recs[-1]["how"] = max(t, recs[-1]["start"]), how

    for a in raw:
        t, code, m = t0 + a[0] * 1000, int(a[1]), a[2]
        e = EVENTS[code] if 0 <= code < len(EVENTS) else "?"
        flag = a[3] if len(a) > 3 else 0
        mid = spec[m]["id"] if isinstance(m, int) and not isinstance(m, bool) and 0 <= m < len(spec) else None
        ev = {"t": _iso(t), "e": e, "moment": mid}
        if flag & 1:
            ev["auto_late"] = True
        if flag & 2:
            ev["reopen"] = True
        events.append(ev)
        if e == "enter" and mid is not None:
            cur, m_start = m, t + spec[m]["lead_s"] * 1000
            recs.append({"i": m, "start": m_start, "paused": 0.0, "end": None})
        elif e == "begin" and recs and recs[-1]["end"] is None:
            m_start = recs[-1]["start"] = t
        elif e in ("tap", "skip", "auto"):
            prev = None if e == "auto" else (cur, m_start)
            close(t, e)
        elif e == "undo" and prev is not None:
            if recs and recs[-1]["i"] != prev[0]:
                recs.pop()
            if recs:
                recs[-1]["end"] = None
                recs[-1].pop("how", None)
            cur, m_start = prev
            prev, status = None, None
        elif e == "pause":
            paused_at = t
        elif e == "resume" and paused_at:
            d = t - paused_at
            in_lead = paused_at < m_start
            m_start += d
            if recs and recs[-1]["end"] is None:
                recs[-1]["start" if in_lead else "paused"] += d
            paused_at = 0.0
        elif e == "stop":
            close(t, "stop")
            status = "stop"
        elif e == "end":
            status = "end"
    last = {r["i"]: r for r in recs}
    out = []
    for i in range(len(spec)):
        r = last.get(i)
        actual = None
        if r is not None and r.get("end") is not None:
            actual = 0 if r.get("how") == "skip" else max(0, _round((r["end"] - r["start"] - r["paused"]) / 1000))
        out.append({"actual_s": actual if r else None, "ended": (r.get("how") or "open") if r else "never"})
    return out, events, status


def decode_web_app_data(data: str, received: datetime | None = None) -> dict:
    """Il ritorno del rito → la seduta, con i tempi veri di ogni momento."""
    o = json.loads(data)
    if not isinstance(o, dict) or o.get("v") != 1 or o.get("k") != "rito":
        raise ValueError("non è il log di un rito")
    t0 = int(o["t0"])
    spec = [{"id": str(x[0]), "type": str(x[1]), "target_s": (x[2] if len(x) > 2 else 0) or 0,
             "max_s": (x[3] if len(x) > 3 else 0) or 0, "lead_s": (x[4] if len(x) > 4 else 0) or 0}
            for x in o.get("M") or []]
    raw = o.get("E") or []
    if not raw or not spec:
        raise ValueError("log senza eventi")
    replayed, events, status = _replay(spec, raw, t0)
    summary = o.get("A")
    truncated = int(o.get("tr") or 0)
    if isinstance(summary, list) and len(summary) == len(spec):
        # i tempi li ha già calcolati il motore, al millisecondo: valgono quelli (anche se il log è stato tagliato)
        acts = [{"actual_s": None if int(a[0]) < 0 else int(a[0]), "ended": str(a[1])} for a in summary]
        approx = False
    else:
        acts, approx = replayed, truncated > 0
    moments = [{"id": m["id"], "type": m["type"], "planned_s": m["target_s"] or None, "max_s": m["max_s"] or None,
                "actual_s": a["actual_s"], "ended": a["ended"],
                "over_max": bool(m["max_s"] and a["actual_s"] and a["actual_s"] > m["max_s"])}
               for m, a in zip(spec, acts)]

    def tot(t: str) -> int:
        return sum(x["actual_s"] or 0 for x in moments if x["type"] == t)
    received_at = (received or datetime.now(_tz())).isoformat(timespec="seconds")
    q = o.get("q") if isinstance(o.get("q"), dict) else {}
    return {"kind": "rito", "rito_date": o.get("d") if isinstance(o.get("d"), str) else None,
            "title": str(o.get("n") or "")[:80], "status": status or (o.get("st") if o.get("st") in ("end", "stop") else None),
            "demo": bool(o.get("demo")), "started_at": events[0]["t"], "ended_at": events[-1]["t"],
            "received_at": received_at, "t0_ms": t0, "truncated_events": truncated, "approx": approx,
            "rounds": sum(1 for x in moments if x["type"] == "heat" and (x["actual_s"] or 0) > 0),
            "heat_s": tot("heat"), "cold_s": tot("cold"), "air_s": tot("air"), "rest_s": tot("rest"),
            "moments": moments, "answers": {str(k)[:40]: str(v)[:40] for k, v in list(q.items())[:8]},
            "note": str(o.get("nt") or "")[:280], "events": events, "raw": data}


def store_session(session: dict, root: Path | None = None) -> Path:
    """Salva la seduta. Un reinvio dello stesso rito (stesso t0) riscrive il file solo se porta
    almeno altrettanto: un ritorno più povero non cancella una seduta buona."""
    d = sessions_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    day = session["started_at"][:10]
    ext = ".demo.session.json" if session.get("demo") else ".session.json"
    body = json.dumps(session, indent=1, ensure_ascii=False) + "\n"
    for f in sorted(d.glob(f"{day}*{ext}")):
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(old, dict) and old.get("t0_ms") == session.get("t0_ms"):
            if len(session.get("events") or []) >= len(old.get("events") or []):
                f.write_text(body, encoding="utf-8")
            return f
    path, n = d / f"{day}{ext}", 2
    while path.exists():
        path = d / f"{day}-{n}{ext}"
        n += 1
    path.write_text(body, encoding="utf-8")
    return path


def _min(sec: float) -> str:
    m = _round(sec / 60)
    return "meno di un minuto" if m <= 0 else "un minuto" if m == 1 else f"{m} minuti"


def reply_text(s: dict) -> str:
    a, b = s["started_at"][11:16], s["ended_at"][11:16]
    words = {1: "un passaggio", 2: "due passaggi", 3: "tre passaggi"}.get(s["rounds"], f"{s['rounds']} passaggi")
    parts = [f"{words} nel calore, {_min(s['heat_s'])} in tutto"] if s["rounds"] else ["fermato alla soglia"]
    if s["cold_s"]:
        parts.append(f"acqua fredda {_min(s['cold_s'])}")
    if s["rest_s"]:
        parts.append(f"riposo {_min(s['rest_s'])}")
    tag = "" if s.get("status") == "end" else " — interrotto"
    tail = " (log tagliato: tempi approssimati)" if s.get("approx") else ""
    return (f"✓ Rito registrato ({a}–{b}){tag}{' (prova a secco)' if s.get('demo') else ''}: "
            + "; ".join(parts) + f".{tail}")


def diary_entry(s: dict) -> dict:
    """Quello che va nel diario del giorno della seduta, in `movement.sauna`."""
    out = {"done": s["rounds"] > 0, "rounds": s["rounds"], "heat_min": _round(s["heat_s"] / 60),
           "cold_min": round(s["cold_s"] / 60, 1), "rest_min": _round(s["rest_s"] / 60),
           "started_at": s["started_at"][11:16], "ended_at": s["ended_at"][11:16],
           "status": s.get("status"), "source": "rito"}
    if s.get("approx"):
        out["approx"] = True
    return out


def write_diary(s: dict, root: Path | None = None) -> Path | None:
    """`movement.sauna` nel diario del giorno in cui il rito è cominciato. Unisce, non sostituisce:
    resta ciò che c'era (il piano, una nota), e una seduta fatta non viene coperta da una fermata alla soglia."""
    day = s["started_at"][:10]
    p = _root(root) / "data" / "logs" / f"{day}.json"
    try:
        log = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"date": day, "morning": {}, "goals_tracking": []}
    except (OSError, ValueError):
        return None                                    # un diario illeggibile non si riscrive
    if not isinstance(log, dict):
        return None
    mv = log.get("movement")
    if not isinstance(mv, dict):
        mv = {"text": mv} if mv not in (None, "", [], {}) else {}
    old = mv.get("sauna")
    old = old if isinstance(old, dict) else ({"note": old} if old not in (None, "", [], {}) else {})
    entry = diary_entry(s)
    if old.get("source") == "rito" and (old.get("rounds") or 0) > 0 and entry["rounds"] == 0:
        return p
    mv["sauna"] = {**old, **entry, "done": entry["done"] or bool(old.get("done"))}
    log["movement"] = mv
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def receive(data: str, root: Path | None = None) -> tuple[Path, dict | None, str]:
    """Il ritorno arrivato dal telefono → (file, seduta o None se illeggibile, risposta da mandare). Niente rete."""
    try:
        session = decode_web_app_data(data)
        return store_session(session, root), session, reply_text(session)
    except Exception as e:  # noqa: BLE001 — log illeggibile: salvo il grezzo e lo dico
        d = sessions_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{datetime.now(_tz()).strftime('%Y-%m-%d-%H%M%S-%f')}.session-raw.txt"
        path.write_text(str(data)[:20000], encoding="utf-8")
        return path, None, f"⚠️ Ritorno del rito illeggibile ({e.__class__.__name__}); salvato grezzo in {path.name}"
