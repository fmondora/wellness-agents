"""Hook SessionStart: chiede di accendere Hṛdaya solo nel repo dati e solo se non batte."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session_check.py"


def run(root: Path) -> str:
    env = dict(os.environ, WELLNESS_DATA=str(root))
    return subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env, check=True).stdout


class SessionCheckTest(unittest.TestCase):
    def test_fuori_dal_repo_dati_silenzio(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run(Path(d)), "")

    def test_spento_chiede_di_accendere_acceso_lo_dice(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "data").mkdir(); (root / "data" / "profile.json").write_text("{}")
            ctx = json.loads(run(root))["hookSpecificOutput"]["additionalContext"]
            self.assertIn("NON è in ascolto", ctx)
            spec = importlib.util.spec_from_file_location("session_state", HOOK.parents[1] / "scripts" / "session_state.py")
            ss = importlib.util.module_from_spec(spec)
            os.environ["WELLNESS_DATA"] = str(root)
            try:
                spec.loader.exec_module(ss); ss.beat(["test"])
            finally:
                del os.environ["WELLNESS_DATA"]
            self.assertIn("risulta attivo", json.loads(run(root))["hookSpecificOutput"]["additionalContext"])
