#!/bin/zsh
# Pubblica SOLO asset generici: pagina, motore, illustrazioni del bundle del plugin, voce.
# Niente test, fixture, dati personali (il workout viaggia nel fragment dell'URL).
#
#   WELLNESS_DATA=<repo dati> deploy.sh [--dry-run]
#
# - illustrazioni: assets/img del plugin coach-longevita (ricolorate); in più le SVG generiche
#   che il coach ha scaricato nel repo dati (data/coach-longevita/daily/img/), se c'è WELLNESS_DATA
# - voce: clip del plugin (voice/) + quelle generate nel repo dati (data/coach-longevita/player-voice/)
# - progetto Cloudflare Pages: WORKOUT_PLAYER_PAGES_PROJECT dal .env del repo dati (default workout-player)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/../.." && pwd)"
DATA="${WELLNESS_DATA:-}"
DIST="$(mktemp -d -t workout-player)"
trap 'rm -rf "$DIST"' EXIT
mkdir -p "$DIST/img" "$DIST/voice"
cp "$HERE"/index.html "$HERE"/engine.js "$HERE"/nosleep.mp4 "$DIST/"
cp "$PLUGIN"/assets/img/*.svg "$DIST/img/"
if [[ -n "$DATA" && -d "$DATA/data/coach-longevita/daily/img" ]]; then
  for f in "$DATA"/data/coach-longevita/daily/img/*.svg(N); do
    [[ -e "$DIST/img/${f:t}" ]] || cp "$f" "$DIST/img/"
  done
fi
# clip mancanti (nomi degli esercizi dei player.json): le genera make_voice.py nel repo dati
python3.12 "$HERE/make_voice.py" >/dev/null || echo "make_voice: voce non aggiornata (say/ffmpeg?)" >&2
cp "$HERE"/voice/*.mp3 "$DIST/voice/"
if [[ -n "$DATA" && -d "$DATA/data/coach-longevita/player-voice" ]]; then
  for f in "$DATA"/data/coach-longevita/player-voice/*.mp3(N); do cp "$f" "$DIST/voice/"; done
fi
cat > "$DIST/img/CREDITS.txt" <<'C'
Illustrazioni: Bryl Lim, github.com/bryllim/workout-guide, CC BY-SA 4.0 (ricolorate).
hsw-*: coach-longevita, CC BY-SA 4.0.
C
cat > "$DIST/_headers" <<'H'
/*
  Cache-Control: no-cache
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
/img/*
  Cache-Control: public, max-age=604800
/voice/*
  Cache-Control: public, max-age=604800
H
echo "Pubblico: $(ls "$DIST" | tr '\n' ' ')· img: $(ls "$DIST/img" | wc -l | tr -d ' ') file · voice: $(ls "$DIST/voice" | wc -l | tr -d ' ') clip"
if [[ "${1:-}" == "--dry-run" ]]; then exit 0; fi
PROJECT="workout-player"
if [[ -n "$DATA" && -f "$DATA/.env" ]]; then
  P=$(grep -E '^WORKOUT_PLAYER_PAGES_PROJECT=' "$DATA/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'" || true)
  [[ -n "$P" ]] && PROJECT="$P"
fi
wrangler pages deploy "$DIST" --project-name "$PROJECT" --branch main --commit-dirty=true
