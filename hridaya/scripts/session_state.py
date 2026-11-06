#!/usr/bin/env python3.12
"""Battito della sessione accesa: come il bot sa se Hṛdaya c'è.

`data/telegram/session.json` = {"on": bool, "pid", "started_at", "heartbeat_at", "listening": [...]}

Lo scrive il server MCP del plugin (un battito ogni 30 s) solo dopo che la skill
`servizio` l'ha acceso; quando la sessione Claude si chiude il server muore e il
battito invecchia. Il bot considera attiva la sessione se `on` e il battito ha meno
di `session_heartbeat_max_age_s` secondi (config, default 150).

CLI (per diagnosi o per una sessione senza MCP):
    session_state.py status | beat [--listening a,b] | off
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def path() -> Path:
    return Path(os.environ.get("WELLNESS_DATA") or Path.cwd()) / "data" / "telegram" / "session.json"


def read() -> dict:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(state: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def beat(listening: list[str] | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    st = read()
    if not st.get("on") or st.get("pid") != os.getpid():
        st = {"on": True, "pid": os.getpid(), "started_at": now.isoformat()}
    st["heartbeat_at"] = now.isoformat()
    if listening is not None:
        st["listening"] = listening
    _write(st)
    return st


def off(now: datetime | None = None) -> None:
    st = read()
    st.update(on=False, stopped_at=(now or datetime.now(timezone.utc)).isoformat())
    _write(st)


def age_s(now: datetime | None = None) -> float | None:
    st = read()
    try:
        hb = datetime.fromisoformat(st["heartbeat_at"])
    except (KeyError, ValueError):
        return None
    return ((now or datetime.now(timezone.utc)) - hb).total_seconds()


def is_active(now: datetime | None = None, max_age_s: float = 150) -> bool:
    if not read().get("on"):
        return False
    a = age_s(now)
    return a is not None and a <= max_age_s


def main() -> int:
    ap = argparse.ArgumentParser(description="Battito della sessione di Hṛdaya")
    ap.add_argument("cmd", choices=["status", "beat", "off"])
    ap.add_argument("--listening", default=None)
    a = ap.parse_args()
    if a.cmd == "beat":
        beat(a.listening.split(",") if a.listening else None)
    elif a.cmd == "off":
        off()
    st = read()
    print(json.dumps({**st, "active": is_active(), "age_s": age_s()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
