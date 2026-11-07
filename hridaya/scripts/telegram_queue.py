#!/usr/bin/env python3.12
"""Coda file del canale di Hṛdaya (data/telegram/ nel repo dati).

  inbox.jsonl   messaggi di Francesco (status pending → done) e, con "kind": "system",
                eventi per la sessione accesa (alzata rilevata, seduta registrata…)
  outbox.jsonl  risposte: righe sent=false le spedisce il bot; le righe sent=true sono
                lo storico di ciò che la sessione ha spedito direttamente (tool MCP)

Tutte le scritture passano dal lock `data/telegram/.lock` (bot, sessione e cancello
scrivono negli stessi file). CLI compatibile con la versione del generalista.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def tg_dir() -> Path:
    return Path(os.environ.get("WELLNESS_DATA") or Path.cwd()) / "data" / "telegram"


def inbox_path() -> Path:
    return tg_dir() / "inbox.jsonl"


def outbox_path() -> Path:
    return tg_dir() / "outbox.jsonl"


@contextmanager
def locked():
    d = tg_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / ".lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir() -> None:
    tg_dir().mkdir(parents=True, exist_ok=True)
    for f in (inbox_path(), outbox_path()):
        if not f.exists():
            f.write_text("", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Riscrittura atomica (chiamare dentro `locked()`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with locked():
        ensure_dir()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def enqueue(chat_id: int, text: str, username: str = "",
            reply_to_text: str | None = None, choice: dict | None = None,
            tg_message_id: int | None = None) -> str:
    msg_id = str(uuid.uuid4())
    row = {"id": msg_id, "chat_id": chat_id, "username": username, "text": text,
           "status": "pending", "created_at": _now()}
    if tg_message_id:
        row["tg_message_id"] = tg_message_id   # per mettergli una reazione
    if choice:
        # risposta con un bottone: {"id", "question", "selected": [...], "multi"}
        row["choice"] = choice
    if reply_to_text:
        # testo del messaggio a cui si risponde: matching con le domande aperte del detector
        row["reply_to_text"] = reply_to_text[:300]
    append_jsonl(inbox_path(), row)
    return msg_id


def enqueue_system(event: str, text: str, data: dict | None = None,
                   dedup_key: str | None = None) -> str | None:
    """Evento per la sessione accesa (non un messaggio di Francesco). Idempotente su dedup_key."""
    if dedup_key and any(r.get("dedup_key") == dedup_key for r in read_jsonl(inbox_path())):
        return None
    msg_id = f"sys-{uuid.uuid4().hex[:12]}"
    row = {"id": msg_id, "kind": "system", "event": event, "text": text, "data": data or {},
           "status": "pending", "created_at": _now()}
    if dedup_key:
        row["dedup_key"] = dedup_key
    append_jsonl(inbox_path(), row)
    return msg_id


def list_pending(include_system: bool = True) -> list[dict[str, Any]]:
    return [r for r in read_jsonl(inbox_path()) if r.get("status") == "pending"
            and (include_system or r.get("kind") != "system")]


def get_message(msg_id: str) -> dict[str, Any] | None:
    return next((r for r in read_jsonl(inbox_path()) if r.get("id") == msg_id), None)


def mark_done(msg_id: str) -> bool:
    with locked():
        rows = read_jsonl(inbox_path())
        found = False
        for row in rows:
            if row.get("id") == msg_id:
                row["status"] = "done"
                row["processed_at"] = _now()
                found = True
        if found:
            write_jsonl(inbox_path(), rows)
    return found


def write_reply(msg_id: str, chat_id: int, text: str) -> None:
    append_jsonl(outbox_path(), {"in_reply_to": msg_id, "chat_id": chat_id, "text": text,
                                 "created_at": _now(), "sent": False})


def record_sent(msg_id: str, chat_id: int | None, text: str, via: str = "mcp") -> None:
    """Storico di un invio già fatto (il bot non lo rispedisce)."""
    now = _now()
    append_jsonl(outbox_path(), {"in_reply_to": msg_id, "chat_id": chat_id, "text": text,
                                 "created_at": now, "sent": True, "sent_at": now, "via": via})


def list_unsent_outbox() -> list[dict[str, Any]]:
    return [r for r in read_jsonl(outbox_path()) if not r.get("sent")]


def mark_outbox_sent(in_reply_to: str, chat_id: int, routed: str | None = None) -> None:
    with locked():
        rows = read_jsonl(outbox_path())
        for row in rows:
            if row.get("in_reply_to") == in_reply_to and row.get("chat_id") == chat_id and not row.get("sent"):
                row["sent"] = True
                row["sent_at"] = _now()
                if routed:
                    row["routed"] = routed
        write_jsonl(outbox_path(), rows)


def cmd_pending(_: argparse.Namespace) -> int:
    pending = list_pending()
    if not pending:
        print("Nessun messaggio in coda.")
        return 0
    for p in pending:
        who = "SISTEMA:" + p.get("event", "") if p.get("kind") == "system" else f"chat={p.get('chat_id')}"
        print(f"{p['id']}\t{who}\t{p['text'][:120]}")
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    write_reply(args.id, args.chat_id, args.text)
    print(f"Risposta in coda per {args.id}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    if mark_done(args.id):
        print(f"OK {args.id}")
        return 0
    print(f"ID non trovato: {args.id}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Coda Telegram di Hṛdaya")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending", help="Lista messaggi pending").set_defaults(func=cmd_pending)
    p_reply = sub.add_parser("reply", help="Scrivi risposta in outbox (la spedisce il bot)")
    p_reply.add_argument("--id", required=True)
    p_reply.add_argument("--chat-id", type=int, required=True)
    p_reply.add_argument("--text", required=True)
    p_reply.set_defaults(func=cmd_reply)
    p_done = sub.add_parser("done", help="Marca messaggio inbox come processato")
    p_done.add_argument("--id", required=True)
    p_done.set_defaults(func=cmd_done)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
