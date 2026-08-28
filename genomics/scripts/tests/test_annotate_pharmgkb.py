import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

TSV = ("Clinical Annotation ID\tVariant/Haplotypes\tGene\tLevel of Evidence\t"
       "Level Override\tLevel Modifiers\tScore\tPhenotype Category\tPMID Count\t"
       "Evidence Count\tDrug(s)\tPhenotype(s)\tLatest History Date (YYYY-MM-DD)\t"
       "URL\tSpecialty Population\n"
       "981\trs1000006\tCYPX\t1A\t\t\t100\tMetabolism/PK\t5\t7\tfarmacone\tnessuno\t2026-01-01\thttp://x\t\n"
       "982\tCYP2D6*4\tCYP2D6\t1A\t\t\t90\tMetabolism/PK\t3\t4\taltro\tnessuno\t2026-01-01\thttp://x\t\n"
       "983\trs4242424\tGENEQ\t2B\t\t\t20\tEfficacy\t1\t1\tterzo\tnessuno\t2026-01-01\thttp://x\t\n")


def test_annotate_pharmgkb(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dump = tmp_path / "data" / "dna" / "db" / "pharmgkb"
    dump.mkdir(parents=True)
    (dump / "clinical_annotations.tsv").write_text(TSV)
    n = dna_annotate.annotate_pharmgkb()
    assert n == 1  # solo rs1000006: l'aplotipo *4 e l'rs assente sono esclusi
    row = json.loads((tmp_path / "data/dna/annotated/pharmgkb.jsonl").read_text())
    assert row["level"] == "1A" and row["drugs"] == "farmacone" and row["genotype"] == "AC"


def test_pharmgkb_dump_mancante(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import pytest, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    with pytest.raises(SystemExit, match="pharmgkb.org"):
        dna_annotate.annotate_pharmgkb()
