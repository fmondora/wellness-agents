"""workout_send (fallback del canale): valida e costruisce l'URL col trasporto di Hṛdaya, senza inviare."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "workout_send.py"
FIX = Path(__file__).resolve().parents[2] / "apps" / "workout-player" / "fixtures"


def _run(data, *args):
    import os
    env = {**os.environ, "WELLNESS_DATA": str(data)}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env,
                          cwd=str(data), timeout=30)


def test_dry_run_valido(tmp_path):
    (tmp_path / ".env").write_text("WORKOUT_PLAYER_URL=https://x.pages.dev/\n")
    r = _run(tmp_path, str(FIX / "2026-11-06.player.json"), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OK — URL")


def test_schema_rotto(tmp_path):
    bad = tmp_path / "x.player.json"
    bad.write_text(json.dumps({"blocks": [{"type": "boh", "exercises": []}]}))
    r = _run(tmp_path, str(bad), "--dry-run")
    assert r.returncode == 2 and "boh" in r.stderr
