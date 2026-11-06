#!/usr/bin/env python3.12
"""Elenca i chat_id che hanno scritto al bot (bootstrap manuale di ALLOWED_CHAT_IDS).

1. crea il bot su BotFather e custodisci il token (skill setup: portachiavi o .env)
2. scrivi /start al bot su Telegram
3. python3.12 telegram_get_chat_id.py

Attenzione: getUpdates va in conflitto (409) col bot in esecuzione — fermalo prima.
Il percorso guidato è `telegram_setup.py wait-start --register`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import channel_config as cc  # noqa: E402
import tg_transport as tt  # noqa: E402


def chats(updates: list[dict]) -> list[dict]:
    seen, out = set(), []
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            out.append({"id": cid, "name": chat.get("first_name", ""), "username": chat.get("username", ""),
                        "text": msg.get("text", "")})
    return out


def main() -> int:
    cc.apply_ca_bundle()
    token = cc.bot_token()
    if not token:
        print("Manca il token del bot (portachiavi o .env).", file=sys.stderr)
        return 1
    found = chats(tt.call(token, "getUpdates", timeout=0).get("result") or [])
    if not found:
        print("Nessun messaggio. Invia /start al bot su Telegram e riprova.")
        return 0
    print("Chat ID trovati (ALLOWED_CHAT_IDS=...):\n")
    for c in found:
        print(f"  {c['id']}  — {c['name']} @{c['username']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
