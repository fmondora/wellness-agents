#!/usr/bin/env python3.12
"""Le figure degli esercizi che il catalogo bryllim non ha (voci con `frames` in knowledge/exercise-catalog.json:
il vocabolario CrossFit e funzionale) con Nano Banana Pro (Gemini 3 Pro Image).

Una chiamata per esercizio: un'immagine 16:9 con le due pose affiancate (stessa persona, stessa scala), tagliata
a metà in frame-1 (partenza) e frame-2 (fine), ciascuno portato a quadrato sul fondo delle figure del player.
Esce in assets/img/<slug>-frame-1.webp e -frame-2.webp, accanto alle SVG del bundle (le copiano deploy.sh del player
e scheda_img.py). Lo stile imita i pittogrammi bryllim già in uso: sagoma piena color inchiostro su fondo chiaro.

    esercizio_img.py [<slug>...] [--missing] [--jobs N] [--force] [--list]

Senza slug e con --missing: tutte le voci con `frames` che non hanno ancora la figura. La chiave viene da
GOOGLE_API_KEY (mai stampata).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "knowledge" / "exercise-catalog.json"
OUT = ROOT / "assets" / "img"
MODEL = "gemini-3-pro-image-preview"
INK, PAPER = "#1a1a1a", "#f4f4f1"
SIZE = 512

STYLE = (
    "Exercise demonstration pictogram in TWO PANELS side by side, left panel = starting position, right panel = "
    "end position. The SAME adult athlete, gender-neutral, same size and same ground line in both panels, seen in a "
    "clean side or three-quarter view chosen so the movement is unmistakable. "
    f"Style: flat solid silhouette pictogram like a fitness app icon set, one single dark ink colour {INK} for the "
    "body and the equipment, thin paper-coloured gaps where limbs overlap so arms and legs read clearly, no outlines, "
    f"no shading, no gradients, no face details. Plain flat background {PAPER} everywhere. Each figure centred in "
    "its own half with generous margin; nothing crosses the vertical centre line. NO vertical divider line or "
    "separator between the panels, no frame, no border, no arrows, no captions or labels such as start or end, no "
    "text, no letters, no numbers, no logos."
)


def catalog() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["exercises"]


def has_img(slug: str) -> bool:
    return any((OUT / f"{slug}-frame-1.{ext}").exists() for ext in ("svg", "webp"))


def prompt(e: dict) -> str:
    start, end = e["frames"]
    gear = "" if e["equipment"] in ("Bodyweight", "") else f" Equipment: {e['equipment'].lower()}."
    return (f"Exercise: {e['name']}.{gear}\nLeft panel (start): {start}.\nRight panel (end): {end}.\n\n{STYLE}")


def generate(text: str, key: str, model: str) -> bytes:
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}}
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


def flatten(img):
    """Due soli colori, inchiostro e carta, con i bordi morbidi: il fondo del modello varia di tinta da un'immagine
    all'altra e il riempimento del quadrato si vedrebbe come una banda."""
    from PIL import Image
    lum = img.convert("L").point(lambda v: 255 if v < 70 else 0 if v > 190 else round((190 - v) * 255 / 120))
    return Image.composite(Image.new("RGB", img.size, INK), Image.new("RGB", img.size, PAPER), lum)


def split(png: bytes, slug: str) -> list[Path]:
    """Taglia a metà, porta ogni metà a quadrato sul fondo carta, 512 px, webp."""
    from PIL import Image
    img = flatten(Image.open(io.BytesIO(png)).convert("RGB"))
    w, h = img.size
    out = []
    for n, box in ((1, (0, 0, w // 2, h)), (2, (w - w // 2, 0, w, h))):
        half = img.crop(box)
        side = max(half.size)
        sq = Image.new("RGB", (side, side), PAPER)
        sq.paste(half, ((side - half.width) // 2, (side - half.height) // 2))
        dest = OUT / f"{slug}-frame-{n}.webp"
        sq.resize((SIZE, SIZE), Image.LANCZOS).save(dest, "WEBP", quality=82)
        out.append(dest)
    return out


def one(e: dict, key: str, model: str) -> tuple[str, str | None]:
    try:
        files = split(generate(prompt(e), key, model), e["slug"])
        return e["slug"], None if len(files) == 2 else "taglio non riuscito"
    except urllib.error.HTTPError as err:
        return e["slug"], err.read().decode()[:300]
    except (urllib.error.URLError, RuntimeError, TimeoutError, OSError) as err:
        return e["slug"], str(err)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--missing", action="store_true", help="tutte le voci con frames ancora senza figura")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    by_slug = {e["slug"]: e for e in catalog() if e.get("frames")}
    if a.list:
        for s in by_slug:
            print(("✓ " if has_img(s) else "· ") + s)
        return 0
    want = a.slugs or ([s for s in by_slug if not has_img(s)] if a.missing else [])
    if not want:
        print("niente da fare: passa degli slug o --missing", file=sys.stderr)
        return 0
    bad = [s for s in want if s not in by_slug]
    for s in bad:
        print(f"{s}: non è nel catalogo o non ha le pose (frames)", file=sys.stderr)
    todo = [by_slug[s] for s in want if s in by_slug and (a.force or not has_img(s))]
    if not todo:
        print("hanno già tutte la figura (--force per rifarle)")
        return 1 if bad else 0
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("manca GOOGLE_API_KEY", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{len(todo)} esercizi, {a.jobs} alla volta…", flush=True)
    failed = len(bad)
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        for slug, err in pool.map(lambda e: one(e, key, a.model), todo):
            print(f"{slug}: {'ok' if err is None else 'errore ' + err}", flush=True)
            failed += err is not None
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
