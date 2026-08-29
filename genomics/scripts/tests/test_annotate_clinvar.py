import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

MINI = """##fileformat=VCFv4.1
##fileDate=2026-08-01
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
1\t2000\trs1000002\tA\tG\t.\t.\tRS=1000002;CLNSIG=Pathogenic;CLNDN=Malattia_Finta|Variante;GENEINFO=GENEX:111
2\t3000\trs1000003\tC\tT\t.\t.\tRS=1000003;CLNSIG=Benign;CLNDN=not_provided;GENEINFO=GENEY:222
9\t9999\trs7777777\tG\tA\t.\t.\tRS=7777777;CLNSIG=Pathogenic;CLNDN=Altra;GENEINFO=GENEZ:333
5\t132000\trs1000004\tC\tT\t.\t.\tRS=1000004;CLNSIG=Conflicting_classifications_of_pathogenicity;CLNDN=Incerta;GENEINFO=GENEK:444
5\t132100\trs1000005\tT\tC\t.\t.\tRS=1000005;CLNSIG=Pathogenic;CLNDN=Non_Portata;GENEINFO=GENEW:555
"""


def _mini_vcf(tmp_path) -> Path:
    p = tmp_path / "mini_clinvar.vcf.gz"
    with gzip.open(p, "wt") as fh:
        fh.write(MINI)
    return p


def test_annotate_clinvar_join(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    n = dna_annotate.annotate_clinvar(vcf_path=_mini_vcf(tmp_path))
    # rs7777777 non è nel raw; rs1000004 (Conflicting) è nel raw e l'annotazione lo tiene
    # — è report_clinvar() a filtrarlo fuori, non annotate_clinvar()
    assert n == 4
    rows = [json.loads(l) for l in
            (tmp_path / "data/dna/annotated/clinvar.jsonl").read_text().splitlines()]
    patho = next(r for r in rows if r["rsid"] == "rs1000002")
    assert patho["clnsig"] == "Pathogenic" and patho["genotype"] == "AG"
    assert patho["gene"] == "GENEX"


def test_build_mismatch_blocca(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import pytest, dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt", build="GRCh38")
    with pytest.raises(SystemExit):
        dna_annotate.annotate_clinvar(vcf_path=_mini_vcf(tmp_path))
