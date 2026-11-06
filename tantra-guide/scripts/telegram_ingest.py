#!/usr/bin/env python3.12
"""
Ingest posts from @tibetanbuddha Telegram channel.

Fonte del Kaula (plugin tantra-guide). Legge il canale con un account utente (Telethon),
NON col bot di Hṛdaya: nessun conflitto col canale.

Usage (cwd o WELLNESS_DATA sul repo dati):
    python3.12 telegram_ingest.py [--limit N] [--api-id ID] [--api-hash HASH]

First run requires authentication (phone number + code).
Session is cached in <repo dati>/.telegram_session for subsequent runs.

Saves posts as markdown files in <repo dati>/data/tantra/telegram/ (spazio del Kaula);
se esiste già la cartella legacy guide/tantra/knowledge/telegram/ continua a usare quella.
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto
except ImportError:
    print("telethon not installed. Run: pip3.12 install telethon --break-system-packages")
    sys.exit(1)

# Paths
PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
_LEGACY = PROJECT_ROOT / "guide" / "tantra" / "knowledge" / "telegram"
OUTPUT_DIR = Path(os.environ.get("TANTRA_TELEGRAM_DIR") or
                  (_LEGACY if _LEGACY.is_dir() else PROJECT_ROOT / "data" / "tantra" / "telegram"))
SESSION_FILE = str(PROJECT_ROOT / ".telegram_session")

CHANNEL = "tibetanbuddha"


def extract_keywords(text: str) -> list[str]:
    """Extract potential keywords from text."""
    # Common tantric/Buddhist terms to look for
    terms = [
        "spanda", "pratyabhijna", "shiva", "shakti", "dharana",
        "meditazione", "meditation", "vuoto", "emptiness", "shunyata",
        "impermanenza", "impermanence", "compassione", "compassion",
        "consapevolezza", "awareness", "coscienza", "consciousness",
        "tantra", "mantra", "yoga", "dharma", "karma", "buddha",
        "risveglio", "awakening", "silenzio", "silence", "respiro",
        "breath", "mente", "mind", "cuore", "heart", "amore", "love",
        "sofferenza", "suffering", "liberazione", "liberation",
        "presenza", "presence", "osservare", "observe",
        "non-dualità", "nonduality", "advaita",
    ]
    text_lower = text.lower()
    found = [t for t in terms if t in text_lower]
    return found if found else ["general"]


def guess_theme(keywords: list[str]) -> str:
    """Guess a theme from keywords."""
    theme_map = {
        "meditazione": "meditation", "meditation": "meditation",
        "vuoto": "shunyata", "emptiness": "shunyata", "shunyata": "shunyata",
        "impermanenza": "impermanence", "impermanence": "impermanence",
        "compassione": "compassion", "compassion": "compassion",
        "spanda": "spanda", "shakti": "shakti", "shiva": "shiva",
        "consapevolezza": "awareness", "awareness": "awareness",
        "coscienza": "consciousness", "consciousness": "consciousness",
        "respiro": "breath", "breath": "breath",
        "silenzio": "silence", "silence": "silence",
        "amore": "love", "love": "love",
        "sofferenza": "suffering", "suffering": "suffering",
        "liberazione": "liberation", "liberation": "liberation",
        "presenza": "presence", "presence": "presence",
    }
    for kw in keywords:
        if kw in theme_map:
            return theme_map[kw]
    return "teaching"


def sanitize_text(text: str) -> str:
    """Clean up Telegram message text."""
    # Remove excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def main(api_id: int, api_hash: str, limit: int):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check existing files to avoid duplicates
    existing_ids = set()
    for f in OUTPUT_DIR.glob("*.md"):
        # Extract message ID from filename
        parts = f.stem.split("-")
        if len(parts) >= 4:
            existing_ids.add(parts[-1])

    # Gira da launchd, senza nessuno davanti. Il 20/10/2026 il server chiudeva
    # la connessione (rete con ispezione TLS) e il riconnetti automatico di
    # Telethon ha girato 4h40 al 93% di CPU scrivendo 24 MB di errori.
    # Pochi tentativi distanziati, niente auto-reconnect: se non va, si riprova domani.
    client = TelegramClient(SESSION_FILE, api_id, api_hash,
                            connection_retries=3, retry_delay=10, auto_reconnect=False)
    await client.connect()
    if not await client.is_user_authorized():
        if sys.stdin.isatty():
            await client.start()  # primo avvio a mano: telefono + codice
        else:
            # da launchd client.start() resterebbe appeso a chiedere il telefono
            await client.disconnect()
            sys.exit("Sessione Telegram non autorizzata: lancia lo script a mano una volta.")

    saved = 0
    skipped = 0

    async for message in client.iter_messages(CHANNEL, limit=limit):
        if not message.text:
            skipped += 1
            continue

        msg_id = str(message.id)
        if msg_id in existing_ids:
            skipped += 1
            continue

        text = sanitize_text(message.text)
        if len(text) < 20:
            skipped += 1
            continue

        date = message.date.strftime("%Y-%m-%d")
        keywords = extract_keywords(text)
        theme = guess_theme(keywords)

        filename = f"{date}-{msg_id}.md"
        filepath = OUTPUT_DIR / filename

        content = f"""---
date: {date}
source: "@tibetanbuddha"
message_id: {msg_id}
keywords: {keywords}
theme: "{theme}"
---

{text}
"""
        filepath.write_text(content)
        saved += 1
        print(f"  Saved: {filename} ({theme})")

    await client.disconnect()
    print(f"\nDone. Saved: {saved}, Skipped: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest @tibetanbuddha posts")
    parser.add_argument("--limit", type=int, default=50,
                        help="Number of recent posts to fetch (default: 50)")
    parser.add_argument("--api-id", type=int,
                        default=int(os.environ.get("TELEGRAM_API_ID", "0")),
                        help="Telegram API ID (or set TELEGRAM_API_ID env var)")
    parser.add_argument("--api-hash", type=str,
                        default=os.environ.get("TELEGRAM_API_HASH", ""),
                        help="Telegram API hash (or set TELEGRAM_API_HASH env var)")
    args = parser.parse_args()

    if not args.api_id or not args.api_hash:
        print("Error: Telegram API credentials required.")
        print("Get them at https://my.telegram.org/apps")
        print()
        print("Usage:")
        print("  export TELEGRAM_API_ID=12345")
        print("  export TELEGRAM_API_HASH=abc123...")
        print("  python3.12 scripts/telegram_ingest.py")
        sys.exit(1)

    try:
        asyncio.run(asyncio.wait_for(main(args.api_id, args.api_hash, args.limit), timeout=600))
    except (asyncio.TimeoutError, ConnectionError, OSError, EOFError) as e:
        sys.exit(f"Ingest interrotto ({type(e).__name__}: {e}) — riprova al prossimo giro.")
