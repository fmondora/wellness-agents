#!/usr/bin/env python3.12
"""SessionStart (avvio, /clear, resume, compact): Hṛdaya è in ascolto?

Solo dentro un repo dati (c'è data/profile.json). Se il servizio non batte, chiede a Claude di
accenderlo subito con la skill `servizio` (un solo Claude: dev'essere questa sessione). Se batte,
lo dice soltanto. Fuori da un repo dati: silenzio. Mai errori bloccanti.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def context() -> str | None:
    if not (ROOT / "data" / "profile.json").exists():
        return None
    try:
        import session_state
        active = session_state.is_active()
        age = session_state.age_s()
    except Exception:  # noqa: BLE001 — il controllo non deve mai bloccare la sessione
        active, age = False, None
    if active:
        return (f"Hṛdaya: il servizio risulta attivo (ultimo battito {round(age or 0)} s fa). "
                "Se in questa sessione non c'è il Monitor «Hṛdaya: coda e ritmo» (es. dopo /clear), "
                "riarmalo come da skill `servizio` di hridaya, senza dirlo a Francesco.")
    return ("Hṛdaya NON è in ascolto (nessun battito recente). Un solo Claude risponde su Telegram ed è questa "
            "sessione: prima di rispondere a Francesco accendi il servizio con la skill `servizio` del plugin "
            "hridaya, poi digli in una riga che sei in ascolto.")


def main() -> int:
    try:
        ctx = context()
    except Exception:  # noqa: BLE001
        ctx = None
    if ctx:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
