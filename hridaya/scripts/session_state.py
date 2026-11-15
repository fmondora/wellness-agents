#!/usr/bin/env python3.12
"""Battito della sessione accesa: come il bot sa se Hṛdaya c'è.

`data/telegram/session.json` = {"on": bool, "pid", "started_at", "heartbeat_at", "listening": [...],
                                 "listen_at", "listen_pid", "dedicated": bool, "session_id"}

Due segnali distinti:
  heartbeat_at  la sessione è viva (lo scrivono il server MCP ogni 30 s e il watcher)
  listen_at     qualcuno ascolta davvero la coda (lo scrive SOLO il watcher del Monitor)
Una sessione viva col Monitor scaduto e mai riarmato batte ma non ascolta: i messaggi resterebbero
in coda. Per questo `is_active` chiede anche un ascolto recente (`listen_max_s`, default 25': copre il
riarmo e i turni lunghi), il bot sveglia la sessione dedicata se l'ascolto è fermo (telegram_bot.listener_tick) e
`service_session.sh tick` la riavvia se resta fermo.

`dedicated` = il battito viene dalla sessione dedicata (HRIDAYA_SERVICE=1, service_session.sh);
`session_id` = CLAUDE_CODE_SESSION_ID di chi batte (diagnosi). `guard()`: una sessione di lavoro
non ascolta mentre batte la dedicata, e se la vede comparire smette (watcher e server MCP).

Il server MCP batte solo dopo che la skill `servizio` l'ha acceso; quando la sessione Claude si
chiude il server muore e il battito invecchia. Il bot considera attiva la sessione se `on`, il
battito ha meno di `session_heartbeat_max_age_s` secondi (default 150) e l'ascolto meno di
`session_listen_max_age_s` (default 1500: un turno lungo, Kaula o consiglio, può tenere fermo il riarmo).

CLI (per diagnosi o per una sessione senza MCP):
    session_state.py status | beat [--listening a,b] | off
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from contextlib import contextmanager
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
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")       # un tmp per processo: due scrittori non si pestano
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


@contextmanager
def _locked():
    """Server MCP, watcher e custode scrivono lo stesso file: read-modify-write sotto lock."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_name(".session.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def beat(listening: list[str] | None = None, now: datetime | None = None, listener: bool = False) -> dict:
    """Battito. `listener=True`: batte il watcher del Monitor (la coda è ascoltata davvero)."""
    now = now or datetime.now(timezone.utc)
    with _locked():
        st = read()
        if not st.get("on"):
            st = {"on": True, "started_at": now.isoformat()}
        st["heartbeat_at"] = now.isoformat()
        if listener:
            st["listen_at"], st["listen_pid"] = now.isoformat(), os.getpid()
        else:
            st["pid"] = os.getpid()
        if listening is not None:
            st["listening"] = listening
        st["dedicated"] = is_dedicated()
        st["session_id"] = os.environ.get("CLAUDE_CODE_SESSION_ID")
        _write(st)
    return st


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def other_listener(now: datetime | None = None, fresh_s: float = 90) -> int | None:
    """Pid di un altro watcher vivo che sta già ascoltando (due ascoltatori = eventi doppi)."""
    st = read()
    pid, a = st.get("listen_pid"), listen_age_s(now)
    if st.get("on") and st.get("listen_at") and pid and pid != os.getpid() and a is not None and a <= fresh_s \
            and _alive(pid):
        return int(pid)
    return None


def is_dedicated() -> bool:
    return os.environ.get("HRIDAYA_SERVICE") == "1"


def dedicated_elsewhere(max_age_s: float = 150) -> bool:
    """La sessione dedicata è viva (anche se in questo momento non ascolta) e questo processo non è lei.
    Viva basta: se è sorda la sveglia il bot o la riavvia il custode, non una sessione di lavoro."""
    return not is_dedicated() and is_alive(max_age_s=max_age_s) and bool(read().get("dedicated"))


def guard(max_age_s: float = 150) -> str | None:
    """None se questo processo può ascoltare; altrimenti il perché no.

    La sessione dedicata ha sempre la precedenza (ce n'è una sola: tmux la tiene unica).
    Una sessione di lavoro non ascolta mentre batte la dedicata."""
    if dedicated_elsewhere(max_age_s):
        return ("il servizio gira nella sessione dedicata (tmux -L hridaya attach -t hridaya): "
                "qui non parte un secondo ascoltatore")
    return None


def off(now: datetime | None = None) -> None:
    with _locked():
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


def listen_age_s(now: datetime | None = None) -> float | None:
    """Secondi dall'ultimo ascolto vero; se il watcher non ha mai battuto, dall'accensione."""
    st = read()
    try:
        ref = datetime.fromisoformat(st.get("listen_at") or st["started_at"])
    except (KeyError, ValueError, TypeError):
        return None
    return ((now or datetime.now(timezone.utc)) - ref).total_seconds()


def is_alive(now: datetime | None = None, max_age_s: float = 150) -> bool:
    """La sessione c'è (batte), che ascolti o no."""
    if not read().get("on"):
        return False
    a = age_s(now)
    return a is not None and a <= max_age_s


def is_active(now: datetime | None = None, max_age_s: float = 150, listen_max_s: float = 1500) -> bool:
    """La sessione c'è e ascolta la coda: è lei che risponde."""
    if not is_alive(now, max_age_s):
        return False
    la = listen_age_s(now)
    return la is None or la <= listen_max_s


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
    print(json.dumps({**st, "active": is_active(), "alive": is_alive(), "age_s": age_s(),
                      "listen_age_s": listen_age_s()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
