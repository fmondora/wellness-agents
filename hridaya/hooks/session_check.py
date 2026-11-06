#!/usr/bin/env python3.12
"""SessionStart (avvio, /clear, resume, compact): Hṛdaya è in ascolto, e dove?

Solo dentro un repo dati (c'è data/profile.json). Un solo Claude risponde su Telegram: la
**sessione dedicata**, lanciata da `service_session.sh` (tmux, launchd, rinasce ogni notte) con
HRIDAYA_SERVICE=1. Lì l'hook fa accendere il servizio o riarmare il Monitor. In ogni altra
sessione (lavoro, sviluppo) dice soltanto dov'è il servizio e che qui non va acceso: così i
contesti non si mescolano. Fuori da un repo dati: silenzio. Mai errori bloccanti.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
LAUNCHER = Path(__file__).resolve().parent.parent / "scripts" / "service_session.sh"


def is_service_session() -> bool:
    return os.environ.get("HRIDAYA_SERVICE") == "1"


def hook_source() -> str:
    """startup | clear | resume | compact, dallo stdin dell'hook (vuoto → startup)."""
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        return (json.loads(raw).get("source") if raw.strip() else None) or "startup"
    except Exception:  # noqa: BLE001
        return "startup"


def context(source: str = "startup") -> str | None:
    if not (ROOT / "data" / "profile.json").exists():
        return None
    try:
        import session_state
        active = session_state.is_active()
        age = session_state.age_s()
    except Exception:  # noqa: BLE001 — il controllo non deve mai bloccare la sessione
        active, age = False, None
    if is_service_session():
        handoff = ROOT / "data" / "hridaya" / "handoff.md"
        lead = (f"Prima leggi {handoff.relative_to(ROOT)}: le cose aperte lasciate ieri sera. "
                if handoff.exists() else "")
        if source == "startup" or not active:
            return (f"Hṛdaya (sessione dedicata). {lead}Accendi il servizio con la skill `servizio` del "
                    "plugin hridaya, tutti i passi: battito, Monitor, messaggi già in coda.")
        return (f"Hṛdaya (sessione dedicata, dopo {source}): servizio attivo, ultimo battito "
                f"{round(age or 0)} s fa. {lead}Il Monitor «Hṛdaya: coda e ritmo» qui non c'è più: riarmalo "
                "come da skill `servizio`, poi guarda `telegram_inbox` e rispondi ai messaggi rimasti, "
                "senza dirlo a Francesco.")
    try:
        dedicated = bool(session_state.read().get("dedicated"))
    except Exception:  # noqa: BLE001
        dedicated = False
    where = (f"gira nella sessione dedicata (ultimo battito {round(age or 0)} s fa)" if active and dedicated
             else f"batte da un'altra sessione non dedicata ({round(age or 0)} s fa)" if active
             else "non è in ascolto adesso")
    return (f"Hṛdaya {where}. Questa è una sessione di lavoro: NON accendere il servizio, NON armare il "
            "Monitor della coda e non rispondere su Telegram da qui, anche se il servizio è spento. "
            f"La sessione dedicata si avvia con `{LAUNCHER} start <repo dati>` e si guarda con "
            "`tmux -L hridaya attach -t hridaya`. Accenderlo qui serve solo se Francesco lo chiede "
            "esplicitamente e la dedicata non gira (con la dedicata attiva il servizio rifiuta).")


def main() -> int:
    try:
        ctx = context(hook_source())
    except Exception:  # noqa: BLE001
        ctx = None
    if ctx:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
