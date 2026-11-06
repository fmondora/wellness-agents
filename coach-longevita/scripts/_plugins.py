"""Trova gli script di un altro plugin del marketplace wellness-agents.

Fonte unica: hridaya/scripts/_plugins.py — copie identiche in health,
coach-longevita e dream-agent (ogni plugin deve funzionare da solo nella cache).

Ordine: variabile WELLNESS_PLUGIN_<NOME> (cartella scripts) → checkout del
marketplace (<radice>/<plugin>/scripts) → cache dei plugin installati
(<cache>/wellness-agents/<plugin>/<versione>/scripts, la più recente).
Il plugin mancante non è un errore: chi chiama degrada e lo dice.
"""
from __future__ import annotations

import glob
import importlib
import os
import sys
from pathlib import Path


def plugin_scripts(name: str) -> Path | None:
    env = os.environ.get("WELLNESS_PLUGIN_" + name.upper().replace("-", "_"))
    if env:
        return Path(env) if Path(env).is_dir() else None
    here = Path(__file__).resolve().parent
    sibling = here.parent.parent / name / "scripts"
    if sibling.is_dir():
        return sibling
    cands = glob.glob(str(here.parent.parent.parent / name / "*" / "scripts"))
    cands += glob.glob(os.path.expanduser(f"~/.claude/plugins/cache/wellness-agents/{name}/*/scripts"))
    cands = [c for c in cands if os.path.isdir(c)]
    return Path(max(cands, key=os.path.getmtime)) if cands else None


def import_from(plugin: str, module: str):
    """Importa `module` dagli script di `plugin` (ImportError se il plugin non c'è)."""
    if module in sys.modules:
        return sys.modules[module]
    d = plugin_scripts(plugin)
    if d is None:
        raise ImportError(f"plugin {plugin} non trovato")
    if str(d) not in sys.path:
        sys.path.append(str(d))
    return importlib.import_module(module)
