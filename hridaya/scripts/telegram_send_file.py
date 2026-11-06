#!/usr/bin/env python3.12
"""Invia un file (PDF, immagine, qualsiasi documento) su Telegram via sendDocument.

    python3.12 telegram_send_file.py <path> [--caption "testo"] [--chat-id N]

Senza --chat-id usa il primo di ALLOWED_CHAT_IDS nel .env del repo dati.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import channel_config as cc  # noqa: E402
import tg_transport as tt  # noqa: E402


def load_env() -> dict[str, str]:
    """Compatibilità con i vecchi chiamanti (`from telegram_send_file import load_env`)."""
    env = cc.load_env()
    tok = cc.bot_token(env)
    if tok:
        env.setdefault("TELEGRAM_BOT_TOKEN", tok)
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--caption", default="")
    ap.add_argument("--chat-id", type=int, default=None)
    args = ap.parse_args()
    src = Path(args.path)
    if not src.is_file():
        sys.exit(f"File non trovato: {src}")
    cc.apply_ca_bundle()
    env = cc.load_env()
    token = cc.bot_token(env)
    if not token:
        sys.exit("Manca il token del bot (portachiavi o .env)")
    chat_id = args.chat_id or cc.primary_chat_id(env)
    if not chat_id:
        sys.exit("Manca ALLOWED_CHAT_IDS nel .env (oppure passa --chat-id)")
    tt.send_file(token, chat_id, src, args.caption)
    print(f"inviato {src.name} ({src.stat().st_size // 1024} KB) a chat {chat_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
