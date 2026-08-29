import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
FIXTURES = Path(__file__).parent / "fixtures"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import gzip, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    from test_annotate_clinvar import MINI
    vcf = tmp_path / "mini.vcf.gz"
    with gzip.open(vcf, "wt") as fh:
        fh.write(MINI)
    dna_annotate.annotate_clinvar(vcf_path=vcf)


def test_report_panels_scrive_kb(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import dna_report
    out = dna_report.report_panels()
    text = out.read_text()
    assert out == tmp_path / "kb" / "genomica.md"
    assert "## Pathway di Test" in text
    assert "| GENEX | rs1000002 | AG | eterozigote, attività ridotta |" in text
    assert "## Fonti" in text and "GRCh37" in text


def test_report_clinvar_ha_disclaimer_e_solo_patogeniche(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import dna_report
    text = dna_report.report_clinvar().read_text()
    assert text.startswith("# Report ClinVar")
    assert dna_report.DISCLAIMER_CLINICO in text
    assert "rs1000002" in text        # Pathogenic, eterozigote (AG, ALT=G) → portatore
    assert "eterozigote" in text
    assert "rs1000003" not in text    # Benign: fuori dal report
    assert "rs1000004" not in text    # Conflicting: fuori dal report
    assert "rs1000005" not in text    # Pathogenic ma TT, ALT=C → omozigote riferimento
    assert "omozigote riferimento" in text
    assert "Malattia Finta\\|Variante" in text


def test_determinismo(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import dna_report
    a = dna_report.report_panels().read_text()
    b = dna_report.report_panels().read_text()
    assert a == b
