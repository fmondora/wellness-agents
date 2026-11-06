"""Lato canale del player: URL, bottone, decodifica e unione delle sedute (contratto JS → Python)."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import workout_player as wp

TZ = ZoneInfo("Europe/Rome")
APP = Path(__file__).resolve().parent / "fixtures"
# log prodotto da engine.js (encodeLog) sulla seduta reale del 6/11: contratto JS → Python
JS_PAYLOAD = (APP / "2026-11-06.webappdata.txt").read_text(encoding="utf-8")


def _payload(events, t0=1793984400000):
    return json.dumps({"v": 1, "d": "2026-11-06", "n": "Demo", "t0": t0, "st": "end",
                       "B": ["Riscaldamento", "Stacco"],
                       "S": [[0, 0, "p", "Prep Riscaldamento"], [1, 0, "w", "Rower"],
                             [2, 1, "w", "Stacco 5 rip. · 60 kg"], [3, 1, "r", "Recupero"],
                             [4, 1, "w", "Stacco 3 rip. · 80 kg"]],
                       "E": events})


class DecodeTest(unittest.TestCase):
    def test_payload_js_reale(self):
        s = wp.decode_web_app_data(JS_PAYLOAD)
        self.assertEqual(s["status"], "end")
        self.assertEqual(s["started_at"], "2026-11-06T18:00:00+01:00")
        self.assertEqual(s["events"][0]["e"], "start")
        self.assertEqual(s["events"][-1]["e"], "end")
        self.assertEqual(s["blocks"][1], "Deadlift")
        st = next(e for e in s["events"] if e["step"] == 5)
        self.assertEqual(st["block_name"], "Deadlift")
        self.assertEqual(st["kind"], "work")
        self.assertIn("60 kg", st["label"])
        self.assertTrue(any(e.get("auto") for e in s["events"]))

    def test_debrief_decodificato_e_unito(self):
        o = json.loads(_payload([[0, 0, 0], [5, 1, 1], [470, 8, 4]]))
        o["q"] = {"rir": "2", "back": "ferma", "wod": "love"}
        o["nt"] = "x" * 400
        s = wp.decode_web_app_data(json.dumps(o))
        self.assertEqual(s["debrief"]["answers"], {"rir": "2", "back": "ferma", "wod": "love"})
        self.assertEqual(len(s["debrief"]["note"]), 280)
        senza = wp.decode_web_app_data(_payload([[0, 0, 0], [5, 1, 1]]))
        self.assertIsNone(senza["debrief"])
        # una continuazione senza debrief non cancella quello già salvato; uno nuovo lo sostituisce
        self.assertEqual(wp.merge_sessions(s, senza)["debrief"]["answers"]["wod"], "love")
        o["q"] = {"wod": "ok"}
        nuovo = wp.decode_web_app_data(json.dumps(o))
        self.assertEqual(wp.merge_sessions(senza, nuovo)["debrief"]["answers"], {"wod": "ok"})

    def test_timestamp_assoluti_e_auto(self):
        s = wp.decode_web_app_data(_payload([[0, 0, 0], [5, 1, 1], [305, 1, 2, 1], [350, 5, 2], [350, 1, 3],
                                             [440, 1, 4], [470, 5, 4], [470, 8, 4]]))
        self.assertEqual([e["t"][11:19] for e in s["events"][:3]], ["18:00:00", "18:00:05", "18:05:05"])
        self.assertTrue(s["events"][2]["auto"])
        self.assertNotIn("auto", s["events"][1])
        self.assertEqual(s["events"][3]["e"], "done")
        self.assertEqual(wp.reply_text(s), "✓ Seduta registrata (18:00–18:07, 8 eventi)")

    def test_salva_senza_sovrascrivere(self):
        s = wp.decode_web_app_data(_payload([[0, 0, 0], [60, 8, 1]]))
        with tempfile.TemporaryDirectory() as d:
            p1 = wp.save_session(s, Path(d))
            p2 = wp.save_session(s, Path(d))
            self.assertEqual(p1.name, "2026-11-06.session.json")
            self.assertEqual(p2.name, "2026-11-06-2.session.json")
            self.assertEqual(json.loads(p1.read_text())["raw"], s["raw"])

    def test_demo_file_separato_e_flag_reopen(self):
        o = json.loads(_payload([[0, 0, 0], [5, 4, 1], [3600, 3, 1, 2], [3700, 7, 1]]))
        o["demo"] = 1
        s = wp.decode_web_app_data(json.dumps(o))
        self.assertTrue(s["demo"])
        self.assertTrue(s["events"][2]["reopen"])
        self.assertNotIn("auto", s["events"][2])
        self.assertTrue(wp.reply_text(s).endswith("(demo)"))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(wp.save_session(s, Path(d)).name, "2026-11-06.demo.session.json")
            self.assertEqual(wp.save_session(s, Path(d)).name, "2026-11-06-2.demo.session.json")
            real = wp.decode_web_app_data(_payload([[0, 0, 0], [60, 8, 1]]))
            self.assertEqual(wp.save_session(real, Path(d)).name, "2026-11-06.session.json")

    def test_handle_risponde_e_toglie_tastiera(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            p = wp.handle_web_app_data("T", 1, JS_PAYLOAD, Path(d), call=lambda *a, **k: calls.append((a, k)))
            self.assertTrue(p.exists())
        (_, method), kw = calls[0]
        self.assertEqual(method, "sendMessage")
        self.assertTrue(kw["text"].startswith("✓ Seduta registrata (18:00–"))
        self.assertEqual(kw["reply_markup"], {"remove_keyboard": True})

    def test_handle_payload_rotto_salva_grezzo(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            p = wp.handle_web_app_data("T", 1, "non json", Path(d), call=lambda *a, **k: calls.append(k))
            self.assertEqual(p.read_text(), "non json")
        self.assertIn("illeggibile", calls[0]["text"])


class SendTest(unittest.TestCase):
    def test_fixture_valide_e_url(self):
        for f in ("2026-11-06.player.json", "demo.player.json"):
            w = json.loads((APP / f).read_text())
            self.assertEqual(wp.validate_workout(w), [], f)
            url = wp.build_url("https://x.pages.dev/", w)
            self.assertTrue(url.startswith("https://x.pages.dev/#w="))
            self.assertLess(len(url), wp.MAX_PLAIN_URL)

    def test_workout_grande_compresso(self):
        w = {"date": "x", "blocks": [{"type": "timed", "name": f"B{i}", "exercises": [
            {"name": f"Esercizio numero {i}", "time_s": 30, "note": "nota lunga " * 5}]} for i in range(40)]}
        self.assertTrue(wp.encode_fragment(w).startswith("z="))

    def test_validazione(self):
        errs = wp.validate_workout({"blocks": [{"type": "emom", "name": "E", "exercises": [{"name": "a"}]},
                                               {"type": "boh", "exercises": []}]})
        self.assertTrue(any("minutes" in e for e in errs))
        self.assertTrue(any("boh" in e for e in errs))

    def test_bottone_reply_keyboard(self):
        calls = []
        w = json.loads((APP / "demo.player.json").read_text())
        wp.send_player_button("T", 1, w, "https://x.pages.dev", call=lambda *a, **k: calls.append(k))
        kb = calls[0]["reply_markup"]
        self.assertTrue(kb["resize_keyboard"])
        btn = kb["keyboard"][0][0]
        self.assertEqual(btn["text"], "▶️ Avvia allenamento")
        self.assertTrue(btn["web_app"]["url"].startswith("https://x.pages.dev#w="))



T0 = 1793984400000  # 2026-11-06 18:00 Roma


def _cont_payload(events, t0=T0 + 3600_000, cont=T0):
    o = json.loads(_payload(events, t0=t0))
    o["cont"] = cont
    return json.dumps(o)


class ContinuationTest(unittest.TestCase):
    # originale: 18:00 start, 18:00:05 rower, 18:05:05 stacco 60, 18:06 recupero, stop 18:06:30
    ORIG = [[0, 0, 0], [5, 1, 1], [305, 1, 2], [360, 5, 2], [360, 1, 3], [390, 7, 3]]
    # continuazione 19:00: step(cont) + pausa, 19:01 ripresa (reopen), 19:01:40 fatto, 19:02 fine
    CONT = [[0, 1, 4, 4], [0, 2, 4], [60, 3, 4, 2], [100, 5, 4], [100, 8, 4]]

    def test_continuazione_unita_alla_seduta(self):
        calls = []
        call = lambda *a, **k: calls.append(k)  # noqa: E731
        with tempfile.TemporaryDirectory() as d:
            p1 = wp.handle_web_app_data("T", 1, _payload(self.ORIG), Path(d), call=call)
            p2 = wp.handle_web_app_data("T", 1, _cont_payload(self.CONT), Path(d), call=call)
            self.assertEqual(p1, p2)
            self.assertEqual(sorted(f.name for f in Path(d).iterdir()), ["2026-11-06.session.json"])
            s = json.loads(p1.read_text())
        self.assertEqual(len(s["events"]), len(self.ORIG) + len(self.CONT))
        self.assertEqual(s["started_at"][11:19], "18:00:00")
        self.assertEqual(s["ended_at"][11:19], "19:01:40")
        self.assertEqual(s["status"], "end")
        self.assertEqual(len(s["segments"]), 2)
        self.assertTrue(s["segments"][1]["continuation"])
        ts = [datetime.fromisoformat(e["t"]) for e in s["events"]]
        self.assertEqual(ts, sorted(ts))
        cont = next(e for e in s["events"] if e.get("cont"))
        self.assertEqual(cont["t"][11:19], "19:00:00")
        self.assertTrue(any(e.get("reopen") for e in s["events"]))
        self.assertIn("Continuazione registrata", calls[1]["text"])
        self.assertIn("2 parti", calls[1]["text"])

    def test_reinvio_non_duplica(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(2):
                wp.handle_web_app_data("T", 1, _payload(self.ORIG), Path(d), call=lambda *a, **k: None)
            files = list(Path(d).iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(len(json.loads(files[0].read_text())["events"]), len(self.ORIG))

    def test_continuazione_senza_originale(self):
        with tempfile.TemporaryDirectory() as d:
            p = wp.handle_web_app_data("T", 1, _cont_payload(self.CONT), Path(d), call=lambda *a, **k: None)
            self.assertEqual(p.name, "2026-11-06.session.json")
            self.assertTrue(json.loads(p.read_text())["is_continuation"])


class LatestPlayerTest(unittest.TestCase):
    def _w(self, d, day, demo=False, title="x"):
        (Path(d) / f"{day}.player.json").write_text(json.dumps({"title": title, "demo": demo, "blocks": []}))

    def test_ultimo_non_demo_non_futuro(self):
        with tempfile.TemporaryDirectory() as d:
            self._w(d, "2026-11-04", title="vero")
            self._w(d, "2026-11-06", demo=True)
            self._w(d, "2026-11-08", title="futuro")
            (Path(d) / "2026-11-05.json").write_text("{}")
            self.assertEqual(wp.latest_player(Path(d), "2026-11-06").name, "2026-11-04.player.json")

    def test_demo_solo_se_unico(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(wp.latest_player(Path(d), "2026-11-06"))
            self._w(d, "2026-11-06", demo=True)
            self.assertEqual(wp.latest_player(Path(d), "2026-11-06").name, "2026-11-06.player.json")

    def test_menu_comandi(self):
        calls = []
        wp.set_bot_commands("T", call=lambda *a, **k: calls.append((a, k)))
        (_, method), kw = calls[0]
        self.assertEqual(method, "setMyCommands")
        self.assertEqual(kw["scope"], {"type": "all_private_chats"})
        cmds = [c["command"] for c in kw["commands"]]
        self.assertEqual(cmds[0], "allenamento")
        self.assertTrue({"log", "nota", "sonno", "help"} <= set(cmds))
