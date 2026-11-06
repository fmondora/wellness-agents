#!/usr/bin/env python3.12
"""Clip vocali pre-registrate per il player (iOS dentro Telegram non legge speechSynthesis dai timer).

    WELLNESS_DATA=<repo dati> python3.12 make_voice.py [player.json ...]

Genera <slug>.mp3 (voce macOS Samantha, en-US) per le frasi fisse e per ogni nome di esercizio
trovato nelle fixture, nei player.json del coach e nei file passati. Le clip del plugin (voice/)
non si rifanno; le nuove vanno nel repo dati (data/coach-longevita/player-voice/), non nella
cache del plugin. Stampa gli slug creati. Lo slug deve coincidere con voiceSlug() in engine.js.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
BUNDLED = HERE / "voice"
VOICE_DIR = REPO / "data" / "coach-longevita" / "player-voice"
FIXED = {"half-way-there": "Half way there", "ten-seconds": "Ten seconds", "next": "Next"}


def voice_slug(text: str) -> str:
    s = re.sub(r"['’]", "", str(text or "").lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def workout_names(path: str | Path) -> set[str]:
    try:
        w = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {x["name"] for b in w.get("blocks", []) for x in b.get("exercises", []) if x.get("name")}


def make(text: str, slug: str) -> bool:
    out = VOICE_DIR / f"{slug}.mp3"
    if out.exists() or (BUNDLED / f"{slug}.mp3").exists():
        return False
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        aiff = Path(td) / "v.aiff"
        # testo via stdin: un nome che inizia con "-" non diventa un'opzione di say
        subprocess.run(["say", "-v", "Samantha", "-o", str(aiff), "-f", "-"], input=text, text=True, check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff),
                        "-ac", "1", "-ar", "22050", "-b:a", "48k", str(out)], check=True)
    return True


def main(argv: list[str]) -> int:
    texts = dict(FIXED)
    files = glob.glob(str(HERE / "fixtures" / "*.json")) + \
        glob.glob(str(REPO / "data" / "coach-longevita" / "daily" / "*.player.json")) + argv
    for f in files:
        for n in workout_names(f):
            texts.setdefault(voice_slug(n), n)
    created = [slug for slug, text in sorted(texts.items()) if slug and make(text, slug)]
    for slug in created:
        print(slug)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
