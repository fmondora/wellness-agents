#!/usr/bin/env python3.12
"""Coda file per bridge Telegram ↔ Wellness Council."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os
PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
TG_DIR = PROJECT_ROOT / "data" / "telegram"
INBOX = TG_DIR / "inbox.jsonl"
OUTBOX = TG_DIR / "outbox.jsonl"


def ensure_dir() -> None:
    TG_DIR.mkdir(parents=True, exist_ok=True)
    for f in (INBOX, OUTBOX):
        if not f.exists():
            f.write_text("", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dir()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def enqueue(chat_id: int, text: str, username: str = "",
            reply_to_text: str | None = None) -> str:
    msg_id = str(uuid.uuid4())
    row = {
        "id": msg_id,
        "chat_id": chat_id,
        "username": username,
        "text": text,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if reply_to_text:
        # testo del messaggio a cui si sta rispondendo ("rispondi" di Telegram):
        # permette il matching deterministico con le domande aperte dell'engine
        row["reply_to_text"] = reply_to_text[:300]
    append_jsonl(INBOX, row)
    return msg_id


def list_pending() -> list[dict[str, Any]]:
    return [r for r in read_jsonl(INBOX) if r.get("status") == "pending"]


def mark_done(msg_id: str) -> bool:
    rows = read_jsonl(INBOX)
    found = False
    ensure_dir()
    with INBOX.open("w", encoding="utf-8") as f:
        for row in rows:
            if row.get("id") == msg_id:
                row["status"] = "done"
                row["processed_at"] = datetime.now(timezone.utc).isoformat()
                found = True
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return found


def write_reply(msg_id: str, chat_id: int, text: str) -> None:
    append_jsonl(
        OUTBOX,
        {
            "in_reply_to": msg_id,
            "chat_id": chat_id,
            "text": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sent": False,
        },
    )


def list_unsent_outbox() -> list[dict[str, Any]]:
    return [r for r in read_jsonl(OUTBOX) if not r.get("sent")]


def mark_outbox_sent(in_reply_to: str, chat_id: int) -> None:
    rows = read_jsonl(OUTBOX)
    ensure_dir()
    with OUTBOX.open("w", encoding="utf-8") as f:
        for row in rows:
            if row.get("in_reply_to") == in_reply_to and row.get("chat_id") == chat_id:
                row["sent"] = True
                row["sent_at"] = datetime.now(timezone.utc).isoformat()
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_pending(_: argparse.Namespace) -> int:
    pending = list_pending()
    if not pending:
        print("Nessun messaggio in coda.")
        return 0
    for p in pending:
        print(f"{p['id']}\tchat={p['chat_id']}\t{p['text'][:120]}")
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
    parser = argparse.ArgumentParser(description="Telegram queue bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pending = sub.add_parser("pending", help="Lista messaggi pending")
    p_pending.set_defaults(func=cmd_pending)

    p_reply = sub.add_parser("reply", help="Scrivi risposta in outbox")
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