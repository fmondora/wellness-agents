import json
import tempfile
import unittest
from pathlib import Path

from health_sync import day_window, merge_into_log, sync_date


class DayWindowTest(unittest.TestCase):
    def test_luglio_utc_plus_2(self):
        start, end = day_window("2026-07-08")
        self.assertEqual(start, "2026-07-08T00:00:00+02:00")
        self.assertEqual(end, "2026-07-09T00:00:00+02:00")

    def test_gennaio_utc_plus_1(self):
        start, _ = day_window("2026-01-15")
        self.assertEqual(start, "2026-01-15T00:00:00+01:00")


class MergeTest(unittest.TestCase):
    def _base(self, log: dict | None):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "data" / "logs").mkdir(parents=True)
        (tmp / "data" / "fitbit").mkdir(parents=True)
        if log is not None:
            (tmp / "data" / "logs" / "2026-07-08.json").write_text(json.dumps(log))
        return tmp

    def test_merge_su_log_esistente(self):
        base = self._base({"mood": "ok"})
        ok = merge_into_log(base, "2026-07-08",
                            {"date": "2026-07-08", "synced_at": "x", "steps": 100})
        self.assertTrue(ok)
        log = json.loads((base / "data" / "logs" / "2026-07-08.json").read_text())
        self.assertEqual(log["mood"], "ok")                 # non distrugge il log
        self.assertEqual(log["fitbit"], {"steps": 100})     # esclude date/synced_at

    def test_log_inesistente_non_esplode(self):
        base = self._base(None)
        self.assertFalse(merge_into_log(base, "2026-07-08", {"steps": 1}))

    def test_log_corrotto_non_esplode(self):
        base = self._base(None)
        log_file = base / "data" / "logs" / "2026-07-08.json"
        log_file.write_text("{questo non e' json valido")
        self.assertFalse(merge_into_log(base, "2026-07-08", {"steps": 1}))
        # il file corrotto resta intatto, non viene sovrascritto a metà
        self.assertEqual(log_file.read_text(), "{questo non e' json valido")


class _AllFailClient:
    """Fake HealthClient: ogni chiamata di rete fallisce (run senza connessione)."""

    def list_data_points(self, *a, **kw):
        raise ConnectionError("nessuna rete")

    def rollup(self, *a, **kw):
        raise ConnectionError("nessuna rete")

    def daily_rollup(self, *a, **kw):
        raise ConnectionError("nessuna rete")


class EmptyRunGuardTest(unittest.TestCase):
    def test_run_senza_dati_non_scrive_file(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "data" / "fitbit").mkdir(parents=True)

        result = sync_date(_AllFailClient(), tmp, "2026-07-08")

        fields = [k for k in result if k not in ("date", "synced_at")]
        self.assertEqual(fields, [])  # nessun campo dato: solo date/synced_at
        self.assertFalse((tmp / "data" / "fitbit" / "2026-07-08.json").exists())

    def test_run_senza_dati_non_sovrascrive_file_esistente(self):
        tmp = Path(tempfile.mkdtemp())
        fitbit_dir = tmp / "data" / "fitbit"
        fitbit_dir.mkdir(parents=True)
        out_file = fitbit_dir / "2026-07-08.json"
        out_file.write_text(json.dumps({"date": "2026-07-08", "steps": 12345}))

        sync_date(_AllFailClient(), tmp, "2026-07-08")

        # il file precedente (con dati buoni) non viene toccato
        self.assertEqual(json.loads(out_file.read_text())["steps"], 12345)


if __name__ == "__main__":
    unittest.main()
