#!/usr/bin/env python3.12
"""Invia su Telegram una scheda formattata: testo HTML + album di immagini.

    python3.12 telegram_send_rich.py <spec.json> [--chat-id N] [--push]

spec.json è una lista di passi:
    {"text": "<b>HTML</b> di Telegram"}
    {"photos": ["a.png", "b.png"], "caption": "<b>HTML</b>"}   # album, caption sulla prima

Path delle foto relativi alla cartella della spec. HTML ammesso da Telegram:
<b> <i> <u> <s> <code> <pre> <a href> <blockquote>. Gli SVG non sono foto per Telegram:
convertili prima (scheda_img.py --png di coach-longevita).

Di default invia subito (è una consegna chiesta). Con --push passa dal cancello di
Hṛdaya: di notte resta in attesa fino all'alzata (usalo per review e iniziative).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import channel_config as cc  # noqa: E402
import tg_transport as tt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--chat-id")
    ap.add_argument("--push", action="store_true", help="passa dal cancello (silenzio notturno)")
    a = ap.parse_args()
    cc.apply_ca_bundle()
    spec_path = Path(a.spec).resolve()
    steps = json.loads(spec_path.read_text(encoding="utf-8"))
    if a.push:
        import push_gate
        pid = push_gate.submit("", source="send_rich", kind="card",
                               card={"steps": steps, "base": str(spec_path.parent)})
        print(f"Scheda accodata al cancello ({pid}).")
        return 0
    env = cc.load_env()
    token = cc.bot_token(env)
    chat = a.chat_id or cc.primary_chat_id(env)
    if not token or not chat:
        sys.exit("Manca il token del bot o ALLOWED_CHAT_IDS (skill setup di Hṛdaya)")
    n = tt.send_card(token, chat, steps, spec_path.parent)
    print(f"Inviati {n} messaggi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
