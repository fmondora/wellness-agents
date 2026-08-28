import sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_connect_creates_schema_under_wellness_data(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common
    con = dna_common.connect()
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"genotypes", "meta"} <= tables
    assert (tmp_path / "data" / "dna" / "genotypes.db").exists()
    dna_common.set_meta(con, "build", "GRCh37")
    assert dna_common.get_meta(con, "build") == "GRCh37"
    assert dna_common.get_meta(con, "assente") is None
    con.close()


def test_file_sha256_and_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common
    f = tmp_path / "x.txt"
    f.write_text("ciao")
    h = dna_common.file_sha256(f)
    assert len(h) == 64 and h == dna_common.file_sha256(f)
    assert dna_common.load_versions() == {}
    dna_common.save_versions({"clinvar": "2026-08"})
    assert dna_common.load_versions() == {"clinvar": "2026-08"}
