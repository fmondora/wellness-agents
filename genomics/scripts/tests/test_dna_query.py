import gzip, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_lookup_rsid_e_gene(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest, dna_annotate, dna_query
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    res = dna_query.lookup(rsid="rs1000002")
    assert res["genotype"] == "AG"
    assert res["annotations"][0]["layer"] == "panels"
    assert res["annotations"][0]["gene"] == "GENEX"
    by_gene = dna_query.lookup(gene="GENEX")
    assert any(a["rsid"] == "rs1000002" for a in by_gene["annotations"])
    assert dna_query.lookup(rsid="rs404")["genotype"] is None
