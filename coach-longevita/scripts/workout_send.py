#!/usr/bin/env python3.12
"""Fallback: manda il bottone «▶️ Avvia allenamento» (reply keyboard → Mini App del player).

    python3.12 workout_send.py data/coach-longevita/daily/YYYY-MM-DD.player.json [--chat-id N] [--dry-run]

Il canale è di Hṛdaya: in sessione si usa il suo tool `telegram_send_player`. Questo script
serve quando il tool non c'è: usa il trasporto del plugin hridaya (lo trova installato o nel
checkout del marketplace), valida lo schema, genera le clip vocali mancanti (e ripubblica il
player se ne ha create), costruisce WORKOUT_PLAYER_URL (.env del repo dati) + #w=… e invia.
Repo dati: cwd o WELLNESS_DATA.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _plugins import import_from  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "apps" / "workout-player"


def channel():
    """(workout_player, channel_config) del plugin hridaya."""
    try:
        return import_from("hridaya", "workout_player"), import_from("hridaya", "channel_config")
    except ImportError as e:
        sys.exit(f"Canale di Hṛdaya non trovato ({e}): installa il plugin hridaya.")


def ensure_voice(player_json: str) -> None:
    """Clip vocali dei nomi: se ne manca qualcuna la genera e ripubblica il player."""
    made = subprocess.run(["python3.12", str(APP / "make_voice.py"), str(Path(player_json).resolve())],
                          capture_output=True, text=True, check=True).stdout.split()
    if made:
        print(f"Nuove clip vocali: {', '.join(made)} — ripubblico il player")
        subprocess.run(["zsh", str(APP / "deploy.sh")], check=True, capture_output=True,
                       env={**os.environ, "WELLNESS_DATA": os.environ.get("WELLNESS_DATA") or os.getcwd()})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("player_json")
    ap.add_argument("--chat-id")
    ap.add_argument("--dry-run", action="store_true", help="valida e stampa la lunghezza dell'URL, non invia")
    a = ap.parse_args()
    wp, cc = channel()
    w = json.loads(Path(a.player_json).read_text(encoding="utf-8"))
    errs = wp.validate_workout(w)
    if errs:
        print("Workout non valido:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 2
    env = cc.load_env()
    base = env.get("WORKOUT_PLAYER_URL", "")
    if not base:
        print("Manca WORKOUT_PLAYER_URL nel .env del repo dati", file=sys.stderr)
        return 1
    url = wp.build_url(base, w)
    if a.dry_run:
        print(f"OK — URL {len(url)} caratteri ({url.split('#')[1][:2]}…)")
        return 0
    ensure_voice(a.player_json)
    cc.apply_ca_bundle()
    token = cc.bot_token(env)
    chat = a.chat_id or cc.primary_chat_id(env)
    if not token or not chat:
        print("Manca il token del bot o ALLOWED_CHAT_IDS (skill setup di Hṛdaya)", file=sys.stderr)
        return 1
    wp.send_player_button(token, chat, w, base)
    print(f"Bottone inviato ({len(url)} caratteri di URL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
