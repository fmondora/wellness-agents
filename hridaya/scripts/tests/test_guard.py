"""Un solo ascoltatore: la sessione dedicata ha la precedenza, quelle di lavoro cedono."""
import os
import subprocess
import sys
from pathlib import Path

import session_state as ss

WATCH = Path(__file__).resolve().parent.parent / "service_watch.py"


def test_lavoro_cede_alla_dedicata(data, monkeypatch):
    monkeypatch.delenv("HRIDAYA_SERVICE", raising=False)
    assert ss.guard() is None                       # nessuno batte
    ss.beat(["lavoro"])
    assert ss.guard() is None                       # batte una sessione di lavoro: non blocco
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    assert ss.guard() is None                       # la dedicata subentra sempre
    ss.beat(["dedicata"])
    assert ss.read()["dedicated"] is True
    monkeypatch.delenv("HRIDAYA_SERVICE")
    assert "sessione dedicata" in ss.guard()        # ora il lavoro non ascolta
    assert ss.dedicated_elsewhere()


def test_watcher_rifiuta_con_la_dedicata_attiva(data, monkeypatch):
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    ss.beat(["dedicata"])
    env = {**os.environ, "WELLNESS_DATA": str(data)}
    env.pop("HRIDAYA_SERVICE", None)
    p = subprocess.run([sys.executable, str(WATCH), "--max-minutes", "0.01"], capture_output=True, text=True,
                       env=env, cwd=str(data), timeout=30)
    assert p.returncode == 3 and "sessione dedicata" in p.stdout
    p = subprocess.run([sys.executable, str(WATCH), "--max-minutes", "0.01"], capture_output=True, text=True,
                       env={**env, "HRIDAYA_SERVICE": "1"}, cwd=str(data), timeout=30)
    assert p.returncode == 0
