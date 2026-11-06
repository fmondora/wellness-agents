"""Hook SessionStart: accende Hṛdaya solo nella sessione dedicata; le altre sono di lavoro e non lo toccano."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session_check.py"


def run(root: Path, service: bool = False, source: str = "startup") -> str:
    env = dict(os.environ, WELLNESS_DATA=str(root))
    env.pop("HRIDAYA_SERVICE", None)
    if service:
        env["HRIDAYA_SERVICE"] = "1"
    return subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env, check=True,
                          input=json.dumps({"source": source})).stdout


class SessionCheckTest(unittest.TestCase):
    def test_fuori_dal_repo_dati_silenzio(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run(Path(d)), "")

    def test_sessione_dedicata_accende_o_riarma(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "data").mkdir(); (root / "data" / "profile.json").write_text("{}")
            ctx = lambda **k: json.loads(run(root, **k))["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Accendi il servizio", ctx(service=True))
            self.assertIn("sessione di lavoro", ctx())
            self.assertNotIn("Accendi il servizio", ctx())
            (root / "data" / "hridaya").mkdir(); (root / "data" / "hridaya" / "handoff.md").write_text("x")
            self.assertIn("handoff.md", ctx(service=True))
            spec = importlib.util.spec_from_file_location("session_state", HOOK.parents[1] / "scripts" / "session_state.py")
            ss = importlib.util.module_from_spec(spec)
            os.environ["WELLNESS_DATA"] = str(root)
            try:
                spec.loader.exec_module(ss); ss.beat(["test"])
            finally:
                del os.environ["WELLNESS_DATA"]
            self.assertIn("Accendi il servizio", ctx(service=True))          # startup: sempre la skill intera
            self.assertIn("telegram_inbox", ctx(service=True, source="clear"))
            self.assertIn("non dedicata", ctx())                              # il battito di prova non è dedicato
            os.environ["WELLNESS_DATA"] = str(root); os.environ["HRIDAYA_SERVICE"] = "1"
            try:
                ss.beat(["test"])
            finally:
                del os.environ["WELLNESS_DATA"]; del os.environ["HRIDAYA_SERVICE"]
            work = ctx()
            self.assertIn("gira nella sessione dedicata", work)
            self.assertIn("NON armare il Monitor", work)
