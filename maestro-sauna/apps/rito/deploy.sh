#!/bin/zsh
# Pubblica SOLO la pagina, il motore e i suoni: niente test, fixture, dati personali
# (la partitura viaggia nel fragment dell'URL; i suoni sono sintetizzati sul telefono).
#
#   WELLNESS_DATA=<repo dati> deploy.sh [--dry-run]
#
# Progetto Cloudflare Pages: RITO_PLAYER_PAGES_PROJECT dal .env del repo dati (default rito-player).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${WELLNESS_DATA:-}"
DIST="$(mktemp -d -t rito-player)"
trap 'rm -rf "$DIST"' EXIT
cp "$HERE"/index.html "$HERE"/engine.js "$HERE"/sound.js "$HERE"/nosleep.mp4 "$DIST/"
# le figure dei gesti (generate con scripts/rito_img.py): illustrazioni generiche, nessun dato personale
IMGS=("$HERE"/img/*.webp(N))
if (( ${#IMGS} )); then mkdir -p "$DIST/img"; cp "${IMGS[@]}" "$DIST/img/"; fi
# pagina, motore e suoni vanno insieme: la versione nel src evita una pagina nuova col motore vecchio in cache
for f in engine.js sound.js; do
  V="$(shasum "$HERE/$f" | cut -c1-10)"
  sed -i '' "s|<script src=\"$f\"></script>|<script src=\"$f?v=$V\"></script>|" "$DIST/index.html"
  grep -q "$f?v=$V" "$DIST/index.html" || { echo "deploy: versione di $f non applicata" >&2; exit 1; }
done
cat > "$DIST/_headers" <<'H'
/*
  Cache-Control: no-cache
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Robots-Tag: noindex
H
echo "Pubblico: $(ls "$DIST" | tr '\n' ' ')"
if [[ "${1:-}" == "--dry-run" ]]; then exit 0; fi
PROJECT="rito-player"
if [[ -n "$DATA" && -f "$DATA/.env" ]]; then
  P=$(grep -E '^RITO_PLAYER_PAGES_PROJECT=' "$DATA/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'" || true)
  [[ -n "$P" ]] && PROJECT="$P"
fi
wrangler pages deploy "$DIST" --project-name "$PROJECT" --branch main --commit-dirty=true
