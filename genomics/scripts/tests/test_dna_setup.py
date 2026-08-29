import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_bootstrap_senza_rete(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_setup
    res = dna_setup.bootstrap(
        FIXTURES / "sample_23andme.txt",
        with_external=False,
        panels_dir=FIXTURES / "panels")

    assert res["ingested"] == 9
    assert res["layers"] == {"panels": 1}
    assert res["errors"] == []
    assert any("genomica.md" in r for r in res["reports"])

    assert (tmp_path / "data" / "dna" / "genotypes.db").exists()
    assert (tmp_path / "data" / "dna" / "annotated" / "panels.jsonl").exists()
    assert (tmp_path / "kb" / "genomica.md").exists()


def test_bootstrap_idempotente(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_setup
    first = dna_setup.bootstrap(
        FIXTURES / "sample_23andme.txt",
        with_external=False,
        panels_dir=FIXTURES / "panels")
    second = dna_setup.bootstrap(
        FIXTURES / "sample_23andme.txt",
        with_external=False,
        panels_dir=FIXTURES / "panels")

    assert first["ingested"] == 9
    assert second["ingested"] == 0          # già ingestito: nessun nuovo insert
    assert second["layers"] == {"panels": 1}  # i pannelli si riannotano comunque
