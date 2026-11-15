#!/usr/bin/env python3.12
"""Le figure (gesti, 1:1) e le scene (sfondi dei momenti, 9:16) del rito con Nano Banana Pro (Gemini 3 Pro Image): un gesto per immagine, stesso stile
per tutte, sui colori della pagina, salvate in apps/rito/img/<gesto>.webp (le copia deploy.sh).
La chiave viene da GOOGLE_API_KEY (mai stampata).

    rito_img.py <slug> [<slug>...] [--out DIR] [--model M] [--force]
    rito_img.py --list
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "gemini-3-pro-image-preview"
OUT = Path(__file__).resolve().parents[1] / "apps" / "rito" / "img"

STYLE = (
    "Calm flat editorial illustration for a spa ritual guide, like a premium wellness book. "
    "One adult person, gender-neutral, wearing simple dark swim shorts, seen clearly from the side or three-quarter "
    "view so the gesture is unmistakable. Soft rounded shapes, no outlines, subtle grain. "
    "Palette only: deep basalt green-black background #1b211f, figure in warm linen #ede6d6 with soft shading, "
    "water in cool teal #7cc9c4, wood in honey #b9925a, small accents of warm sand #d9b36c. "
    "Minimal setting, generous empty space around the figure, square format. "
    "No text, no letters, no numbers, no logos, no facial details."
)

GESTURES = {
    "kneipp": "Kneipp cold water affusion: the person stands and, with a garden hose held close to the skin, pours a "
              "gentle smooth sheet of cold water on the back of their right leg, from the ankle up to just above the "
              "knee. The water flows softly down the calf like a thin film, no spray. A small soft arrow follows the "
              "leg upward.",
    "tinozza": "Cold plunge in an outdoor round wooden tub (a Finnish-style barrel tub) at dusk: the person sits in "
               "the water up to the chest, calm, forearms resting on the wooden rim, breathing slowly. A few ripples.",
    "doccia": "Warm shower before the sauna: the person under a simple rain shower head, eyes closed, relaxed, steam.",
    "pediluvio": "Warm foot bath: the person sits on a wooden stool with both feet in a wooden basin of warm water, "
                 "a towel over the shoulders.",
    "panca": "Inside a Finnish sauna: the person lies stretched out on the middle wooden bench on a towel that covers "
             "the whole length of the body, relaxed. Hot stove with stones in the corner.",
    "seduto": "Inside a Finnish sauna: the person sits on the lower bench, feet resting on the floor, hands on knees, "
              "getting ready to stand up slowly.",
    "elica": "At the open door of a wooden sauna: the person swings a towel in a wide circle above the head like a "
             "propeller to bring fresh air into the cabin.",
    "gettata": "Inside a Finnish sauna: the person pours a ladle of water from a wooden bucket onto the hot stones of "
               "the stove; a soft cloud of steam rises.",
    "aria": "After the sauna, outdoors in the cool evening: the person walks slowly barefoot on a wooden deck, "
            "breathing through the nose, a towel around the waist.",
    "riposo": "Rest after the sauna: the person lies on a sofa or lounger indoors, covered by a soft blanket up to the "
              "chest, eyes closed, warm socks, a glass of water nearby.",
}

# Le scene: lo sfondo a tutto schermo di ogni tipo di momento, mentre il momento scorre. Nessuna persona (la
# persona è chi guarda), il centro calmo e vuoto (ci sta sopra la clessidra), buio e poco contrasto (sopra ci
# sono parole e bottoni).
SCENE_STYLE = (
    "Same visual language as a calm flat editorial illustration for a spa ritual guide: soft rounded shapes, no "
    "outlines, subtle paper grain. Palette only: deep basalt green-black #1b211f, warm linen #ede6d6 used sparingly, "
    "honey wood #b9925a, warm sand #d9b36c, cool teal #7cc9c4. "
    "Tall vertical composition for a phone screen, FULL-BLEED from edge to edge: no frame, no border, no rounded card, no inset panel, no window shape, no split or stripes at the sides. NO people, no animals. The whole central area of the image is a "
    "calm, dark, almost empty field (an hourglass will be drawn over it): details only along the bottom third and "
    "the far edges. Very dark overall, low contrast, dusk light, a gentle vignette. "
    "No text, no letters, no numbers, no logos."
)
SCENES = {
    "scena-calore": "Inside a Finnish wooden sauna at night, seen from the bench: warm wooden wall planks, the benches "
                    "along the bottom, the stove with hot stones glowing ember-orange in a lower corner, a wooden bucket "
                    "and ladle, a faint wisp of steam. The whole image is bathed in warm deep ember light: background "
                    "from dark burnt brown #2a0f07 at the top to glowing rust #86300d at the bottom, NOT green or black.",
    "scena-freddo": "Outdoors at dusk: a round wooden cold-water tub at the bottom of the frame, still teal water, "
                    "a few pine branches at the edges, the first stars in a deep teal night sky (#04252b to #115560).",
    "scena-aria": "A wooden deck outside the sauna in the cool evening air: the planks at the bottom, a towel on the "
                  "railing at one edge, misty pines far away, a pale sky of grey-green (#1a2526 to #3b5152).",
    "scena-riposo": "A quiet room for resting after the sauna: a lounger with a soft folded blanket at the bottom, "
                    "a glass of water on a small wooden table, a warm lamp glowing low, deep moss-green darkness "
                    "(#171d14 to #37472c).",
    "scena-prima": "A changing area before the sauna: folded linen towels on a wooden shelf at the bottom, slippers, "
                   "a water bottle, a wooden bucket, soft warm light from the side, basalt green-black darkness.",
    "scena-dopo": "After the ritual: a cup of herbal tea with a thin thread of steam, warm socks and a small bottle "
                  "of oil on a wooden tray at the bottom, a candle, calm basalt and warm sand darkness.",
}


def prompt(slug: str) -> tuple[str, str]:
    """→ (testo, rapporto d'aspetto)"""
    if slug in SCENES:
        return f"{SCENES[slug]}\n\nStyle: {SCENE_STYLE}", "9:16"
    return f"{GESTURES[slug]}\n\nStyle: {STYLE}", "1:1"


def generate(slug: str, key: str, model: str) -> bytes:
    text, ratio = prompt(slug)
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio}},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise RuntimeError(f"nessuna immagine nella risposta ({json.dumps(data)[:300]})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.slugs:
        print("\n".join([*GESTURES, *SCENES]))
        return 0
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("manca GOOGLE_API_KEY", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for slug in a.slugs:
        if slug not in GESTURES and slug not in SCENES:
            print(f"{slug}: gesto sconosciuto", file=sys.stderr)
            bad += 1
            continue
        dest = a.out / f"{slug}.webp"
        if dest.exists() and not a.force:
            print(f"{slug}: c'è già ({dest})")
            continue
        try:
            png = generate(slug, key, a.model)
            if shutil.which("cwebp"):        # la pagina carica .webp: 768 px bastano per mezzo schermo
                with tempfile.NamedTemporaryFile(suffix=".png") as t:
                    t.write(png)
                    t.flush()
                    subprocess.run(["cwebp", "-quiet", "-q", "82", "-resize", "768", "0", t.name, "-o", str(dest)], check=True)
            else:
                dest = dest.with_suffix(".png")
                dest.write_bytes(png)
                print(f"{slug}: manca cwebp, lascio il png (la pagina vuole .webp)", file=sys.stderr)
            print(f"{slug}: {dest}")
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as e:
            msg = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else str(e)
            print(f"{slug}: errore {msg}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
