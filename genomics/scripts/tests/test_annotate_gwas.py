import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

HEADER = "DATE ADDED TO CATALOG\tPUBMEDID\tFIRST AUTHOR\tDATE\tJOURNAL\tLINK\tSTUDY\tDISEASE/TRAIT\tINITIAL SAMPLE SIZE\tREPLICATION SAMPLE SIZE\tREGION\tCHR_ID\tCHR_POS\tREPORTED GENE(S)\tMAPPED_GENE\tUPSTREAM_GENE_ID\tDOWNSTREAM_GENE_ID\tSNP_GENE_IDS\tUPSTREAM_GENE_DISTANCE\tDOWNSTREAM_GENE_DISTANCE\tSTRONGEST SNP-RISK ALLELE\tSNPS\tMERGED\tSNP_ID_CURRENT\tCONTEXT\tINTERGENIC\tRISK ALLELE FREQUENCY\tP-VALUE\tPVALUE_MLOG\tP-VALUE (TEXT)\tOR or BETA\t95% CI (TEXT)\tPLATFORM [SNPS PASSING QC]\tCNV\tMAPPED_TRAIT\tMAPPED_TRAIT_URI\tSTUDY ACCESSION\tGENOTYPING TECHNOLOGY"


def _mini_tsv(tmp_path) -> Path:
    def row(snps, trait, p, orb, gene, acc):
        cells = [""] * 38
        cells[7], cells[14], cells[21], cells[27], cells[30], cells[36] = trait, gene, snps, p, orb, acc
        return "\t".join(cells)
    p = tmp_path / "mini_gwas.tsv"
    p.write_text("\n".join([HEADER,
        row("rs1000003", "Tratto Finto A", "3E-12", "1.21", "GENEY", "GCST900001"),
        row("rs5555555 x rs1000007", "Tratto Finto B", "2E-9", "0.88", "GENEW", "GCST900002"),
        row("rs4242424", "Tratto Assente", "1E-8", "1.1", "GENEQ", "GCST900003")]))
    return p


def test_annotate_gwas(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    n = dna_annotate.annotate_gwas(tsv_path=_mini_tsv(tmp_path))
    assert n == 2
    rows = [json.loads(l) for l in
            (tmp_path / "data/dna/annotated/gwas.jsonl").read_text().splitlines()]
    multi = next(r for r in rows if r["rsid"] == "rs1000007")
    assert multi["trait"] == "Tratto Finto B" and multi["genotype"] == "GG"
    assert multi["study"] == "GCST900002"
