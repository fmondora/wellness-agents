#!/usr/bin/env python3.12
"""Le novità di una versione nuova di Hṛdaya, dette a chi usa il canale. Una volta per versione.

Le note stanno in NOVITA.md alla radice del plugin, scritte per la persona (non per chi sviluppa):
  ## 0.11.0
  - Le canzoni: chiedi «fammi una canzone di…» e il Kaula la scrive, il Mac la canta.
Il bot, all'avvio, confronta la versione installata con l'ultima annunciata
(data/hridaya/release.json): di giorno le novità partono subito come messaggio a sé, di notte
vanno nel cancello e escono col messaggio del mattino. Alla prima installazione (canale mai usato)
non annuncia nulla; un repo già in uso senza release.json riceve le novità della versione corrente.
Versioni senza note: niente messaggio. Una riga che comincia con «[canzoni]», «[vocali]» o «[sauna]»
parla di una funzione facoltativa: esce solo se quella funzione è accesa.

    release.py preview      il messaggio che partirebbe adesso (non lo manda)
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "NOVITA.md"
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MAX_CHARS = 3500


def _v(s: str) -> tuple[int, ...]:
    """«0.10» = «0.10.0»; suffissi («-beta», « — 15/11») ignorati."""
    m = re.match(r"\s*(\d+(?:\.\d+)*)", s or "")
    parts = [int(x) for x in m.group(1).split(".")] if m else [0]
    return tuple((parts + [0, 0, 0])[:3])


def version() -> str:
    try:
        return str(json.loads(MANIFEST.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def parse(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cur = None
    for ln in text.splitlines():
        m = re.match(r"^##\s+v?(\d+(?:\.\d+)*)\b", ln)
        if m:
            cur = ".".join(map(str, _v(m.group(1))))
            out[cur] = []
        elif cur and re.match(r"^\s*[-*]\s+\S", ln):
            out[cur].append(re.sub(r"^\s*[-*]\s+", "", ln).strip())
        elif cur and out[cur] and ln.startswith("  ") and ln.strip():
            out[cur][-1] += " " + ln.strip()       # riga a capo dello stesso punto
    return out


def features() -> dict[str, bool]:
    """Funzioni facoltative accese in questo repo dati (per le righe «[tag] …» delle note)."""
    out = {}
    try:
        import song
        out["canzoni"] = bool(song.config())
    except Exception:  # noqa: BLE001
        out["canzoni"] = False
    try:
        import voice_note
        out["vocali"] = bool(voice_note.config())
    except Exception:  # noqa: BLE001
        out["vocali"] = False
    try:
        import rito_player
        out["sauna"] = rito_player.installed() and bool(cc.load_env().get("RITO_PLAYER_URL"))
    except Exception:  # noqa: BLE001
        out["sauna"] = False
    return out


def _filter(lines: list[str], feats: dict[str, bool]) -> list[str]:
    out = []
    for x in lines:
        m = re.match(r"^\[([a-z]+)\]\s*(.*)$", x)
        if not m:
            out.append(x)
        elif feats.get(m.group(1)):
            out.append(m.group(2))
    return out


def pending(announced: str, current: str, notes: dict[str, list[str]],
            feats: dict[str, bool] | None = None) -> list[tuple[str, list[str]]]:
    feats = features() if feats is None else feats
    out = []
    for v, items in notes.items():
        lines = _filter(items, feats)
        if lines and _v(announced) < _v(v) <= _v(current):
            out.append((v, lines))
    return sorted(out, key=lambda x: _v(x[0]))


def message(items: list[tuple[str, list[str]]], current: str) -> str:
    head = f"🫀 <b>Hṛdaya {html.escape(current, quote=False)}</b> — cosa c'è di nuovo"
    body = []
    for v, lines in reversed(items):                # la più recente in alto
        if len(items) > 1:
            body.append(f"\n<b>{html.escape(v, quote=False)}</b>")
        body += [f"• {html.escape(x, quote=False)}" for x in lines]
    text = head + "\n" + "\n".join(body) + "\n\n/help per i comandi."
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 40].rsplit("\n", 1)[0] + "\n…\n\n/help per i comandi."
    return text


def state_path() -> Path:
    return cc.data_root() / "data" / "hridaya" / "release.json"


def _in_use() -> bool:
    """Il canale è già stato usato (non è una prima installazione)."""
    root = cc.data_root() / "data"
    return any((root / x).exists() for x in ("telegram/inbox.jsonl", "telegram/push.jsonl", "hridaya/service.json"))


def announce(send: Callable[[str], str | None] | None = None, current: str | None = None,
             notes_text: str | None = None, feats: dict[str, bool] | None = None) -> str | None:
    """Manda (o mette nel cancello) le novità non ancora annunciate. → id/esito, o None.
    `send(text)`: chi spedisce; default il cancello."""
    current = current or version()
    if not current:
        return None
    if notes_text is None:
        try:
            notes_text = NOTES.read_text(encoding="utf-8")
        except OSError:
            notes_text = ""
    notes = parse(notes_text)
    p = state_path()
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = None
    p.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(st, dict) or not st.get("announced"):
        if not _in_use():
            p.write_text(json.dumps({"announced": current}, indent=1) + "\n", encoding="utf-8")
            return None                              # prima installazione: niente elenco di tutto
        older = [v for v in notes if _v(v) < _v(current)]
        st = {"announced": max(older, key=_v) if older else "0"}   # già in uso: solo la versione corrente
        if not older:
            notes = {v: x for v, x in notes.items() if _v(v) == _v(current)}
    if _v(st["announced"]) >= _v(current):
        return None
    items = pending(st["announced"], current, notes, feats)
    pid = None
    if items:
        text = message(items, current)
        if send is None:
            import push_gate
            pid = push_gate.submit(text, source="release", kind="push", parse_mode="HTML",
                                   push_id=f"release-{current}")
        else:
            pid = send(text)
    p.write_text(json.dumps({"announced": current}, indent=1) + "\n", encoding="utf-8")
    return pid


if __name__ == "__main__":
    if sys.argv[1:] == ["preview"]:
        try:
            st = json.loads(state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        items = pending(st.get("announced") or "0", version(), parse(NOTES.read_text(encoding="utf-8")))
        # (anteprima: senza stato mostra tutto lo storico; l'annuncio vero ne manda meno)
        print(message(items, version()) if items else "niente da annunciare")
        raise SystemExit(0)
    print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
    raise SystemExit(1)
