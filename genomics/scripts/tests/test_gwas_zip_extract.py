import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_extract_first_tsv_da_zip(tmp_path):
    import dna_annotate

    zip_path = tmp_path / "gwas_catalog.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "non è un tsv, va ignorato")
        zf.writestr("gwas-catalog-associations_ontology-annotated-full.tsv",
                    "DISEASE/TRAIT\tSNPS\nTratto Finto\trs1000001\n")

    dest = tmp_path / "gwas_catalog.tsv"
    out = dna_annotate._extract_first_tsv(zip_path, dest)

    assert out == dest
    assert dest.exists()
    content = dest.read_text()
    assert content.startswith("DISEASE/TRAIT\tSNPS")
    assert "rs1000001" in content
