import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_annotate_panels(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    n = dna_annotate.annotate_panels(FIXTURES / "panels")
    assert n == 1  # rs1000002 c'è (AG), rs9999999 no
    out = tmp_path / "data" / "dna" / "annotated" / "panels.jsonl"
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows[0]["rsid"] == "rs1000002"
    assert rows[0]["effect"] == "eterozigote, attività ridotta"
    assert rows[0]["relevance"] == "media"
    con = dna_common.connect()
    assert con.execute("SELECT COUNT(*) FROM annotations_panels").fetchone()[0] == 1
    # idempotenza: seconda run identica, non duplicata
    assert dna_annotate.annotate_panels(FIXTURES / "panels") == 1
    assert con.execute("SELECT COUNT(*) FROM annotations_panels").fetchone()[0] == 1


def test_genotipo_invertito(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    con = dna_common.connect()
    con.execute("UPDATE genotypes SET genotype='GA' WHERE rsid='rs1000002'")
    con.commit()
    assert dna_annotate.annotate_panels(FIXTURES / "panels") == 1
