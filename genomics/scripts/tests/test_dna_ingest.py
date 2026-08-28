import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_txt(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest
    res = dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    assert res["status"] == "ok"
    assert res["inserted"] == 9          # tutte tranne il no-call
    assert res["skipped_nocall"] == 1
    con = dna_common.connect()
    row = con.execute(
        "SELECT genotype, chrom, pos, build FROM genotypes WHERE rsid='rs1000002'"
    ).fetchone()
    assert row == ("AG", "1", 2000, "GRCh37")
    # l'indel resta (DI è un genotipo valido del chip), il no-call no
    assert con.execute("SELECT COUNT(*) FROM genotypes").fetchone()[0] == 9
    assert dna_common.get_meta(con, "build") == "GRCh37"


def test_ingest_idempotente(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest
    first = dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    second = dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    assert first["status"] == "ok"
    assert second["status"] == "already_ingested"
