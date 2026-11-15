#!/usr/bin/env python3.12
"""Quale versione di hridaya gira in questo processo, e qual è l'ultima installata.

Ogni versione installata vive in una cartella sua della cache (`…/cache/wellness-agents/hridaya/0.13.0/`):
un processo partito da `0.12.1` resta su `0.12.1` anche dopo l'installazione della `0.13.0`. Dal checkout
del marketplace (sviluppo) la cartella è sempre la stessa e conta il plugin.json che cambia sul posto.

Lo usano il server MCP (avvisa la sessione che gira con codice vecchio) e il bot (riparte da solo:
launchd lo rilancia e lo shim prende la versione più alta).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # cartella del plugin (versione o checkout)
_VER = re.compile(r"^\d+(?:\.\d+)*$")


def _v(s: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in s.split("."))
    except ValueError:
        return (0,)


def _manifest(d: Path) -> str:
    try:
        return str(json.loads((d / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def running(root: Path = ROOT) -> str:
    """La versione della cartella da cui è partito questo processo (letta adesso: vale per il checkout)."""
    return _manifest(root)


def latest(root: Path = ROOT) -> str:
    """L'ultima versione installata: la più alta fra le cartelle sorelle (cache), o il manifest (checkout)."""
    if not _VER.match(root.name):
        return _manifest(root)
    vers = [d.name for d in root.parent.iterdir() if d.is_dir() and _VER.match(d.name)
            and (d / ".claude-plugin" / "plugin.json").exists()]
    return max(vers, key=_v) if vers else _manifest(root)
