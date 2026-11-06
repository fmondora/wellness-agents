"""Debrief del player: FC e passi blocco per blocco (workout_fitbit), sulle sedute decodificate dal canale."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from _plugins import import_from

import workout_fitbit
from workout_fitbit import aggregate, segments, summary

wp = import_from("hridaya", "workout_player")   # contratto: session.json come lo salva il bot
TZ = ZoneInfo("Europe/Rome")


def _payload(events, t0=1793984400000):
    return json.dumps({"v": 1, "d": "2026-11-06", "n": "Demo", "t0": t0, "st": "end",
                       "B": ["Riscaldamento", "Stacco"],
                       "S": [[0, 0, "p", "Prep Riscaldamento"], [1, 0, "w", "Rower"],
                             [2, 1, "w", "Stacco 5 rip. · 60 kg"], [3, 1, "r", "Recupero"],
                             [4, 1, "w", "Stacco 3 rip. · 80 kg"]],
                       "E": events})


T0 = 1793984400000


def _cont_payload(events, t0=T0 + 3600_000, cont=T0):
    o = json.loads(_payload(events, t0=t0))
    o["cont"] = cont
    return json.dumps(o)


class DemoTest(unittest.TestCase):
    def test_fitbit_ignora_demo(self):
        o = json.loads(_payload([[0, 0, 0], [60, 8, 1]])); o["demo"] = 1
        with tempfile.TemporaryDirectory() as d:
            f = wp.save_session(wp.decode_web_app_data(json.dumps(o)), Path(d))
            with mock.patch.object(sys, "argv", ["x", "2026-11-06", "--file", str(f)]), \
                 mock.patch.object(workout_fitbit, "minutes_series", side_effect=AssertionError("rete")):
                self.assertEqual(workout_fitbit.main(), 1)


class FitbitAggregateTest(unittest.TestCase):
    def setUp(self):
        # 18:00:00 start (prep) · 18:00:05 rower · 18:05:05 stacco · 18:06:00 recupero · 18:07:30 stacco · 18:08:00 fine
        self.session = wp.decode_web_app_data(_payload(
            [[0, 0, 0], [5, 1, 1], [305, 1, 2], [360, 5, 2], [360, 1, 3], [450, 1, 4], [480, 5, 4], [480, 8, 4]]))
        t0 = datetime(2026, 11, 6, 18, 0, tzinfo=TZ)
        # FC finta a 10 s: 100 nel riscaldamento, 160 nello stacco, 125 nel recupero
        self.hr = []
        for k in range(0, 60):
            t = t0 + timedelta(seconds=10 * k)
            v = 100 if t < t0 + timedelta(seconds=305) else 160 if t < t0 + timedelta(seconds=360) \
                else 125 if t < t0 + timedelta(seconds=450) else 155
            self.hr.append({"t": t, "avg": v, "max": v + 3, "min": v - 2})
        self.steps = {t0 + timedelta(minutes=m): 60 for m in range(9)}  # 60 passi/min

    def test_segmenti(self):
        segs = segments(self.session)
        self.assertEqual([s["step"] for s in segs], [0, 1, 2, 3, 4])
        self.assertEqual(segs[-1]["end"].strftime("%H:%M:%S"), "18:08:00")

    def test_aggregazione_per_blocco_e_passo(self):
        r = aggregate(self.session, self.hr, 10, self.steps)
        b0, b1 = r["blocks"]
        self.assertEqual(b0["start"][11:19], "18:00:05")       # il prep non conta nel blocco
        self.assertEqual(b0["hr_avg"], 100.0)
        self.assertEqual(b0["min_over_120"], 0)
        self.assertEqual(b1["start"][11:19], "18:05:05")
        self.assertEqual(b1["hr_max"], 163)
        self.assertEqual(b1["hr_min"], 123)
        # stacco 18:05:05–18:06:00 → 5 campioni (18:05:10…18:05:50) a 160; recupero 9 a 125; stacco 3 a 155
        self.assertEqual(b1["min_over_150"], round((5 + 3) * 10 / 60, 1))
        self.assertEqual(b1["min_over_120"], round((5 + 9 + 3) * 10 / 60, 1))
        self.assertEqual(b1["steps"], 175)                      # 175 s × 1 passo/s
        work = [s for s in r["steps"] if s["kind"] == "work"]
        self.assertEqual(work[1]["hr_avg"], 160.0)
        self.assertEqual(r["session"]["steps"], 480)
        self.assertIn("Stacco", summary({"source": {"hr": "rollup 10s", "steps": "60s"}, **r}))

    def test_minuto_senza_max_min(self):
        hr = [{"t": p["t"], "avg": p["avg"]} for p in self.hr[::6]]
        r = aggregate(self.session, hr, 60, self.steps)
        self.assertIsNotNone(r["blocks"][0]["hr_max"])

    def test_blocco_saltato(self):
        s = wp.decode_web_app_data(_payload([[0, 0, 0], [5, 1, 1], [60, 4, 1], [60, 7, 1]]))
        s["blocks"].append("Extra")
        r = aggregate(s, self.hr, 10, self.steps)
        self.assertEqual(len(r["blocks"]), 1)
        self.assertEqual(r["steps"][-1]["end"][11:19], "18:01:00")



class ContinuationFitbitTest(unittest.TestCase):
    ORIG = [[0, 0, 0], [5, 1, 1], [305, 1, 2], [360, 5, 2], [360, 1, 3], [390, 7, 3]]
    CONT = [[0, 1, 4, 4], [0, 2, 4], [60, 3, 4, 2], [100, 5, 4], [100, 8, 4]]

    def test_fitbit_sulla_seduta_unita_salta_il_buco(self):
        with tempfile.TemporaryDirectory() as d:
            wp.handle_web_app_data("T", 1, _payload(self.ORIG), Path(d), call=lambda *a, **k: None)
            p = wp.handle_web_app_data("T", 1, _cont_payload(self.CONT), Path(d), call=lambda *a, **k: None)
            s = json.loads(p.read_text())
        t0 = datetime(2026, 11, 6, 18, 0, tzinfo=TZ)
        hr = [{"t": t0 + timedelta(seconds=10 * k), "avg": 90, "max": 92, "min": 88} for k in range(6 * 70)]
        steps = {t0 + timedelta(minutes=m): 60 for m in range(70)}
        r = aggregate(s, hr, 10, steps)
        segs = segments(s)
        self.assertEqual([x["step"] for x in segs], [0, 1, 2, 3, 4])
        self.assertEqual(segs[3]["end"].strftime("%H:%M:%S"), "18:06:30")   # il recupero finisce allo stop
        self.assertEqual(segs[4]["start"].strftime("%H:%M:%S"), "19:00:00")
        self.assertEqual(r["session"]["duration_s"], 390 + 100)              # il buco di 53' non conta
        self.assertEqual(r["session"]["parts"], 2)
        self.assertEqual(r["session"]["steps"], 490)
        stacco = next(b for b in r["blocks"] if b["block"] == 1)
        self.assertEqual(stacco["duration_s"], 85 + 100)
