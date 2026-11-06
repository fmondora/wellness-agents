#!/usr/bin/env python3.12
"""Bottoni di risposta sotto un messaggio di Hṛdaya (inline keyboard di Telegram).

Hṛdaya propone le opzioni; Francesco risponde con un tocco; la scelta torna nella coda
come un messaggio suo (con il campo `choice`), e la sessione la smista come le altre.

  scelta singola  un tocco = risposta; la tastiera diventa una riga «✓ <scelta>»
  scelta multipla i tocchi accendono/spengono ✓; «Conferma» manda la risposta

Stato in data/telegram/choices.json (lock condiviso con la coda):
  {"<cid>": {"question", "options": [[label...]...], "multi", "selected": [i...],
             "status": "open"|"answered", "created_at", "answered_at"?}}
callback_data: "ch:<cid>:<i>" (opzione), "ch:<cid>:ok" (conferma), "ch:noop" (inerte).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import telegram_queue as tq

MAX_OPTIONS = 12
MAX_LABEL = 40
MAX_PER_ROW = 4          # righe automatiche
MAX_ROW = 8              # limite di Telegram per riga
MAX_TOAST = 200
MAX_SEEN = 50
KEEP_DAYS = 30
CONFIRM = "Conferma"


class ChoiceError(ValueError):
    pass


def path():
    return tq.tg_dir() / "choices.json"


def _load() -> dict[str, dict]:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st: dict[str, dict]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    st = {k: v for k, v in st.items() if v.get("created_at", "") >= cutoff}
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def normalize(options: Any) -> list[list[str]]:
    """["a","b"] → righe da MAX_PER_ROW; [["a","b"],["c"]] → righe come date."""
    if not isinstance(options, list) or not options:
        raise ChoiceError("buttons.options: lista non vuota di etichette (o di righe di etichette)")
    if all(isinstance(o, str) for o in options):
        rows = [options[i:i + MAX_PER_ROW] for i in range(0, len(options), MAX_PER_ROW)]
    elif all(isinstance(r, list) and r and all(isinstance(o, str) for o in r) for r in options):
        rows = options
    else:
        raise ChoiceError("buttons.options: o tutte stringhe o tutte righe di stringhe")
    if any(len(r) > MAX_ROW for r in rows):
        raise ChoiceError(f"al massimo {MAX_ROW} bottoni per riga")
    flat = [o.strip() for r in rows for o in r]
    if len(flat) > MAX_OPTIONS:
        raise ChoiceError(f"al massimo {MAX_OPTIONS} opzioni")
    if any(not o or len(o) > MAX_LABEL for o in flat):
        raise ChoiceError(f"etichette da 1 a {MAX_LABEL} caratteri")
    if len(set(flat)) != len(flat):
        raise ChoiceError("etichette ripetute")
    return [[o.strip() for o in r] for r in rows]


def _labels(c: dict) -> list[str]:
    return [o for r in c["options"] for o in r]


def markup(cid: str, c: dict) -> dict:
    """Tastiera dallo stato: le opzioni accese hanno ✓ davanti; nella multipla c'è Conferma."""
    sel, i, kb = set(c.get("selected") or []), 0, []
    for row in c["options"]:
        out = []
        for label in row:
            out.append({"text": ("✓ " if i in sel else "") + label, "callback_data": f"ch:{cid}:{i}"})
            i += 1
        kb.append(out)
    if c.get("multi"):
        kb.append([{"text": f"✔︎ {CONFIRM}", "callback_data": f"ch:{cid}:ok"}])
    return {"inline_keyboard": kb}


def answered_markup(selected: list[str]) -> dict:
    text = "✓ " + (", ".join(selected) if selected else "nessuna")
    return {"inline_keyboard": [[{"text": text[:64], "callback_data": "ch:noop"}]]}


def create(options: Any, question: str, multi: bool = False) -> tuple[str, dict]:
    """Registra una scelta aperta → (cid, reply_markup)."""
    rows = normalize(options)
    cid = uuid.uuid4().hex[:10]
    c = {"question": (question or "")[:500], "options": rows, "multi": bool(multi), "selected": [],
         "status": "open", "created_at": datetime.now(timezone.utc).isoformat()}
    with tq.locked():
        st = _load()
        st[cid] = c
        _save(st)
    return cid, markup(cid, c)


def discard(cid: str) -> None:
    """L'invio non è partito: la scelta non deve restare aperta."""
    with tq.locked():
        st = _load()
        if st.pop(cid, None) is not None:
            _save(st)


def _toast(t: str) -> str:
    return t if len(t) <= MAX_TOAST else t[:MAX_TOAST - 1] + "…"


def tap(data: str, tap_id: str | None = None) -> dict:
    """Un tocco su un bottone → cosa fare.

    {"action": "noop"|"stale"|"toggle"|"answer", "toast", "markup"?, "cid"?, "question"?, "selected"?}
    toggle: aggiorna la tastiera; answer: tastiera inerte + messaggio in coda.
    tap_id (callback_query.id): un tocco già visto (bot riavviato, update riletto) non si riapplica.
    """
    parts = (data or "").split(":")
    if parts[:1] != ["ch"] or len(parts) == 2 and parts[1] == "noop":
        return {"action": "noop", "toast": ""}
    if len(parts) != 3:
        return {"action": "stale", "toast": "Bottone non valido"}
    cid, arg = parts[1], parts[2]
    with tq.locked():
        st = _load()
        c = st.get(cid)
        if not c:   # scaduta o mai registrata: via la tastiera morta
            return {"action": "stale", "toast": "Questa domanda è scaduta", "markup": {"inline_keyboard": []}}
        if tap_id and tap_id in (c.get("seen") or []):
            return {"action": "noop", "toast": ""}
        labels = _labels(c)
        if c.get("status") == "answered":
            sel = [labels[i] for i in c.get("selected") or [] if i < len(labels)]
            return {"action": "stale", "toast": "Hai già risposto", "markup": answered_markup(sel)}
        if arg == "ok":
            if not c.get("multi"):
                return {"action": "stale", "toast": "Bottone non valido"}
            idx = sorted(c.get("selected") or [])
            if not idx:
                return {"action": "stale", "toast": "Scegli almeno un'opzione"}
        else:
            try:
                i = int(arg)
            except ValueError:
                return {"action": "stale", "toast": "Bottone non valido"}
            if not 0 <= i < len(labels):
                return {"action": "stale", "toast": "Bottone non valido"}
            if c.get("multi"):
                sel = set(c.get("selected") or [])
                sel.symmetric_difference_update({i})
                c["selected"] = sorted(sel)
                if tap_id:
                    c["seen"] = (c.get("seen") or [])[-(MAX_SEEN - 1):] + [tap_id]
                st[cid] = c
                _save(st)
                return {"action": "toggle", "toast": _toast(("✓ " if i in sel else "✗ ") + labels[i]),
                        "markup": markup(cid, c)}
            idx = [i]
        c["selected"], c["status"] = idx, "answered"
        c["answered_at"] = datetime.now(timezone.utc).isoformat()
        st[cid] = c
        _save(st)
    chosen = [labels[i] for i in idx]
    return {"action": "answer", "toast": _toast("✓ " + ", ".join(chosen)), "cid": cid,
            "question": c.get("question", ""), "selected": chosen, "multi": bool(c.get("multi")),
            "markup": answered_markup(chosen)}


def reopen(cid: str) -> None:
    """La risposta non è entrata in coda: la domanda torna aperta (lui può ritoccare)."""
    with tq.locked():
        st = _load()
        c = st.get(cid)
        if c and c.get("status") == "answered":
            c["status"] = "open"
            c.pop("answered_at", None)
            _save(st)


def answer_text(chosen: list[str]) -> str:
    """Il testo del messaggio in coda: come se l'avesse scritto lui."""
    return ", ".join(chosen)
