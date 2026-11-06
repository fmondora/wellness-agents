#!/usr/bin/env python3.12
"""Richiesta di push verso il cancello di Hṛdaya — contratto su file, nessun import tra plugin.

Chi produce un messaggio d'iniziativa (detector, review, promemoria) NON scrive
più nella outbox Telegram: accoda una richiesta in `data/telegram/push.jsonl`.
Il cancello di Hṛdaya (plugin `hridaya`, `scripts/push_gate.py`) decide quando
consegnarla: silenzio dall'ora di letto all'alzata rilevata, fusione dei
messaggi contemporanei, red flag sempre subito.

Schema riga (fonte unica: `hridaya/scripts/push_gate.py`, docstring):
    {"id", "created_at", "source", "kind", "priority": "normal"|"red_flag",
     "text", "status": "pending", "meta": {...}}

Il lock (`data/telegram/.lock`) è lo stesso del cancello e della coda.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _tg_dir() -> Path:
    return Path(os.environ.get("WELLNESS_DATA", Path.cwd())) / "data" / "telegram"


@contextmanager
def _locked():
    d = _tg_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / ".lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def request_push(text: str, source: str, kind: str = "push", priority: str = "normal",
                 meta: dict | None = None, push_id: str | None = None) -> str:
    """Accoda una richiesta di push. Idempotente su `push_id` se dato."""
    row = {
        "id": push_id or f"{source}-{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "kind": kind,
        "priority": priority,
        "text": text,
        "status": "pending",
        "meta": meta or {},
    }
    path = _tg_dir() / "push.jsonl"
    with _locked():
        if push_id and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("id") == push_id:
                        return push_id
                except json.JSONDecodeError:
                    continue
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row["id"]
