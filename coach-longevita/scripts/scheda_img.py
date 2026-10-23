#!/usr/bin/env python3
"""Prepara le illustrazioni degli esercizi per la scheda (markdown/PDF/Telegram).

    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scheda_img.py SLUG [SLUG ...] \
        [--dest data/coach-longevita/daily/img] [--png]

Per ogni slug del catalogo mette in --dest i frame SVG (frame-1 = partenza,
frame-2 = fine, a volte frame-3). Ordine delle fonti:
  1. già presenti in --dest → non li tocca (possono essere stati ritoccati)
  2. bundle del plugin (assets/img/, già ricolorati per fondo chiaro)
  3. download da `_svg_url` del catalogo, ricolorati: gli originali sono
     disegnati in bianco per un sito a fondo scuro, su carta sono invisibili.

--png converte anche in PNG (Telegram non accetta SVG come foto) in
--dest/png/<file>.svg.png: qlmanage su macOS, altrimenti rsvg-convert o cairosvg.

Stampa una riga TSV per frame: slug, svg, png — path relativi alla cartella
che contiene --dest (dove stanno il .md e il .telegram.json del giorno).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "assets" / "img"
CATALOG = ROOT / "knowledge" / "exercise-catalog.json"
INK = "#1a1a1a"
WHITE_FILL = re.compile(r'fill="(?:#fff|#ffffff|white)"', re.I)


def recolor(svg: str) -> str:
    return WHITE_FILL.sub(f'fill="{INK}"', svg)


def fetch(url: str) -> str:
    # curl prima: usa il trust store di sistema, quindi passa anche dietro
    # proxy con ispezione TLS (CA aziendale nel portachiavi, non in certifi).
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "30", url],
                           capture_output=True, check=True)
        return r.stdout.decode("utf-8")
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def download(slug: str, url_tpl: str, dest: Path) -> list[Path]:
    got = []
    for n in (1, 2, 3):
        url = url_tpl.replace("{slug}", slug).replace("frame-1", f"frame-{n}")
        try:
            svg = fetch(url)
        except Exception:
            if n <= 2:
                print(f"# {slug}: frame-{n} non scaricabile ({url})", file=sys.stderr)
            continue
        out = dest / f"{slug}-frame-{n}.svg"
        out.write_text(recolor(svg), encoding="utf-8")
        got.append(out)
    return got


def frames(slug: str, dest: Path, url_tpl: str) -> list[Path]:
    pattern = f"{slug}-frame-*.svg"
    have = sorted(dest.glob(pattern)) or sorted(dest.glob(f"{slug}.svg"))
    if have:
        return have
    bundled = sorted(BUNDLE.glob(pattern)) or sorted(BUNDLE.glob(f"{slug}.svg"))
    if bundled:
        for f in bundled:
            shutil.copy2(f, dest / f.name)
        return [dest / f.name for f in bundled]
    return download(slug, url_tpl, dest)


def to_png(svg: Path, png_dir: Path) -> Path | None:
    out = png_dir / f"{svg.name}.png"
    if out.exists() and out.stat().st_mtime >= svg.stat().st_mtime:
        return out
    if shutil.which("qlmanage"):
        subprocess.run(["qlmanage", "-t", "-s", "900", "-o", str(png_dir), str(svg)],
                       check=False, capture_output=True)
    elif shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", "900", "-o", str(out), str(svg)], check=False)
    else:
        try:
            import cairosvg
            cairosvg.svg2png(url=str(svg), write_to=str(out), output_width=900)
        except ImportError:
            pass
    return out if out.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--dest", default="data/coach-longevita/daily/img")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()

    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    png_dir = dest / "png"
    if a.png:
        png_dir.mkdir(exist_ok=True)
    url_tpl = json.loads(CATALOG.read_text(encoding="utf-8"))["_svg_url"]
    base = dest.parent

    missing = 0
    for slug in a.slugs:
        found = frames(slug, dest, url_tpl)
        if not found:
            print(f"# {slug}: nessuna immagine (né in bundle né scaricabile)", file=sys.stderr)
            missing += 1
            continue
        for svg in found:
            png = to_png(svg, png_dir) if a.png else None
            if a.png and png is None:
                print(f"# {svg.name}: conversione PNG non riuscita", file=sys.stderr)
            print("\t".join([slug, str(svg.relative_to(base)),
                             str(png.relative_to(base)) if png else ""]))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
