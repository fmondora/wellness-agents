#!/usr/bin/env python3.12
"""Il servizio di Hṛdaya nella sessione: uno stream di eventi per il tool Monitor.

Una riga su stdout = una notifica alla sessione. Emette:
  MSG <id> <testo>        nuovo messaggio di Francesco in coda
  SYS <evento> <id> <testo>  evento di sistema in coda (wake, workout_session, red_flag)
  SERA <data>             è l'ora del messaggio della sera (config evening_message)
  MATTINO <data>          alzata registrata e messaggio del mattino non ancora partito
  REVIEW <job>            review di un coach dovuta (calendario di Hṛdaya)
Ogni cue di programmazione esce una volta al giorno (stato in data/hridaya/service.json).
Batte anche il battito della sessione (`session_state.beat`) ogni 30 s, così il bot sa
che Hṛdaya c'è anche se il server MCP non è collegato.

    python3.12 service_watch.py [--max-minutes 29]

Esce da solo prima della scadenza del Monitor (30'): la skill lo riarma.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import push_gate  # noqa: E402
import session_state  # noqa: E402
import telegram_queue as tq  # noqa: E402

LISTENING = ["coda Telegram", "sera", "alzata", "review dei coach"]


def cue_path() -> Path:
    return cc.data_root() / "data" / "hridaya" / "service.json"


def load_cues() -> dict:
    try:
        return json.loads(cue_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cues(c: dict) -> None:
    cue_path().parent.mkdir(parents=True, exist_ok=True)
    cue_path().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def scheduled_cues(now: datetime, cues: dict, plugins: set[str] | None = None) -> list[str]:
    """Programmazioni dovute adesso (e segnate in `cues`, una volta al giorno)."""
    out = []
    cfg = cc.rhythm()
    today = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    st = push_gate.load_state()
    if cfg["evening_message"] <= hhmm < cfg["bedtime"] and cues.get("evening") != today \
            and st.get("evening_sent") != today:
        cues["evening"] = today
        out.append(f"SERA {today}")
    late = hhmm >= cfg["wake"]["late_cutoff"]
    if (st.get("wake") or {}).get(today) and st.get("wake_sent") != today and cues.get("wake") != today \
            and st.get("wake_skipped") != today and not late:
        cues["wake"] = today
        out.append(f"MATTINO {today}")
    import hridaya_calendar as hc
    done = cues.setdefault("review", {})
    for job in hc.due(now, plugins=plugins):
        if done.get(job["id"]) != today:
            done[job["id"]] = today
            out.append(f"REVIEW {job['id']}")
    return out


def queue_events(seen: set[str]) -> list[str]:
    """Righe in coda mai emesse (anche fra un riarmo e l'altro: `seen` è persistito)."""
    out = []
    for r in tq.list_pending():
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        if r.get("kind") == "system" and r.get("event") == "wake":
            day = (r.get("data") or {}).get("date")
            st = push_gate.load_state()
            if day and (st.get("wake_sent") == day or st.get("wake_skipped") == day):
                continue   # il mattino è già chiuso: non invitare a scriverlo
        text = " ".join(str(r.get("text", "")).split())[:200]
        if r.get("kind") == "system":
            out.append(f"SYS {r.get('event')} {r['id']} {text}")
        else:
            out.append(f"MSG {r['id']} {text}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=29)
    ap.add_argument("--interval", type=float, default=2)
    a = ap.parse_args()
    if not cc.is_data_repo():
        print(f"ERRORE: {cc.data_root()} non è un repo dati (manca data/profile.json)")
        return 1
    try:
        from _plugins import plugin_scripts
        plugins = {p for p in ("coach-longevita", "dream-agent") if plugin_scripts(p)}
    except Exception:  # noqa: BLE001
        plugins = None
    end = time.monotonic() + a.max_minutes * 60
    seen: set[str] = set(load_cues().get("seen") or [])
    last_beat = 0.0
    last_sched = 0.0
    while time.monotonic() < end:
        before = len(seen)
        lines = queue_events(seen)
        if len(seen) != before or time.monotonic() - last_sched >= 60:
            cues = load_cues()
            if time.monotonic() - last_sched >= 60:
                lines += scheduled_cues(datetime.now(cc.tz()), cues, plugins)
                last_sched = time.monotonic()
            pending = {r["id"] for r in tq.list_pending()}
            cues["seen"] = sorted(i for i in seen if i in pending)[-500:]   # solo le ancora in coda
            save_cues(cues)
        for line in lines:
            print(line, flush=True)
        if time.monotonic() - last_beat >= 30:
            session_state.beat(LISTENING)
            last_beat = time.monotonic()
        time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
