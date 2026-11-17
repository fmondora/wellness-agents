import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
FIXTURES = Path(__file__).parent / "fixtures"

HEAD = "relation,display_relation,x_index,x_id,x_type,x_name,x_source,y_index,y_id,y_type,y_name,y_source\n"
EDGES = [
    ("drug_protein", "enzyme", "drug", "Farmacone", "gene/protein", "GENEX"),
    ("drug_protein", "enzyme", "gene/protein", "GENEX", "drug", "Farmacone"),
    ("drug_protein", "target", "drug", "Farmacone", "gene/protein", "RECETTORE"),
    ("drug_drug", "synergistic interaction", "drug", "Farmacone", "drug", "Secondo"),
    ("drug_drug", "synergistic interaction", "drug", "Secondo", "drug", "Farmacone"),
    ("drug_drug", "synergistic interaction", "drug", "Farmacone", "drug", "Estraneo"),
    ("drug_drug", "synergistic interaction", "drug", "Solitario", "drug", "Estraneo"),
    ("contraindication", "contraindication", "drug", "Farmacone", "disease", "severe hypertension"),
    ("drug_effect", "side effect", "drug", "Secondo", "effect/phenotype", "Headache"),
    ("disease_protein", "associated with", "disease", "essential hypertension", "gene/protein", "GENEX"),
    ("phenotype_protein", "associated with", "effect/phenotype", "Migraine", "gene/protein", "GENEX"),
    ("disease_protein", "associated with", "disease", "essential hypertension", "gene/protein", "GENER"),
    ("pathway_protein", "interacts with", "pathway", "Via comune", "gene/protein", "GENEX"),
    ("pathway_protein", "interacts with", "pathway", "Via comune", "gene/protein", "GENEP"),
    ("pathway_protein", "interacts with", "pathway", "Via solitaria", "gene/protein", "GENEX"),
    ("protein_protein", "ppi", "gene/protein", "GENEX", "gene/protein", "GENEP"),
]
PGKB = ("Clinical Annotation ID\tVariant/Haplotypes\tGene\tLevel of Evidence\tPhenotype Category\tDrug(s)\n"
        "981\trs1000006\tGENEP\t1A\tMetabolism/PK\tfarmacone\n")
# Record ClinVar senza allele alternativo: restano non valutabili anche quando un altro record dello stesso
# rsid ha un ALT (rs1000008: il record benigno con ALT=T non dice nulla sull'allele del risk_factor).
EXTRA_CLINVAR = ("22\t21000\trs1000008\tC\t.\t.\t.\tRS=1000008;CLNSIG=risk_factor;CLNDN=X;GENEINFO=GENER:9\n"
                 "22\t21000\trs1000008\tC\tT\t.\t.\tRS=1000008;CLNSIG=Benign;CLNDN=Y;GENEINFO=GENER:9\n"
                 "17\t38000\trs1000007\tA\t.\t.\t.\tRS=1000007;CLNSIG=drug_response;CLNDN=Z;GENEINFO=GENEU:8\n")
CONFIG = {"graph": {"drugs": ["farmacone", "Secondo", "Solitario", "Introvabile"],
                    "conditions": ["Severe Hypertension", "essential hypertension", "migraine", "Headache",
                                   "Malattia Inventata"]}}


def _setup(tmp_path, monkeypatch, config=CONFIG):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest, dna_annotate, dna_graph
    from test_annotate_clinvar import MINI
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    vcf = tmp_path / "mini.vcf.gz"
    with gzip.open(vcf, "wt") as fh:
        fh.write(MINI + EXTRA_CLINVAR)
    dna_annotate.annotate_clinvar(vcf_path=vcf)
    dump = tmp_path / "data" / "dna" / "db" / "pharmgkb"
    dump.mkdir(parents=True)
    (dump / "clinical_annotations.tsv").write_text(PGKB)
    dna_annotate.annotate_pharmgkb()
    kg = tmp_path / "kg.csv"
    kg.write_text(HEAD + "".join(f"{r},{d},0,1,{xt},{xn},S,1,2,{yt},{yn},S\n" for r, d, xt, xn, yt, yn in EDGES))
    if config is not None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "genomics.json").write_text(
            config if isinstance(config, str) else json.dumps(config))
    return dna_graph, dna_graph.load(csv_path=kg)


def _kinds(tmp_path):
    kinds = {}
    for line in (tmp_path / "data/dna/annotated/graph.jsonl").read_text().splitlines():
        r = json.loads(line)
        kinds.setdefault(r["kind"], []).append(r)
    return kinds


def test_load_tiene_solo_le_relazioni_utili(tmp_path, monkeypatch):
    _, n = _setup(tmp_path, monkeypatch)
    assert n == len(EDGES) - 1  # protein_protein fuori


def test_annotate_incrocia_farmaci_e_geni(tmp_path, monkeypatch):
    g, _ = _setup(tmp_path, monkeypatch)
    g.annotate()
    k = _kinds(tmp_path)
    enz = [r for r in k["drug_gene"] if r["object"] == "GENEX"]
    assert len(enz) == 1 and enz[0]["subject"] == "Farmacone" and enz[0]["relation"] == "enzyme"
    assert "rs1000002 AG" in enz[0]["variants"] and "ClinVar" in enz[0]["variants"]
    assert [r for r in k["drug_gene"] if r["object"] == "RECETTORE"][0]["variants"] == ""
    assert [(r["subject"], r["object"]) for r in k["drug_drug"]] == [("Farmacone", "Secondo")]
    assert sorted((r["subject"], r["object"]) for r in k["drug_condition"]) == [
        ("Farmacone", "severe hypertension"), ("Secondo", "Headache")]
    assert [r["subject"] for r in k["drug_missing"]] == ["Introvabile"]
    assert [r["subject"] for r in k["condition_missing"]] == ["Malattia Inventata"]
    assert [r["subject"] for r in k["drug_nolinks"]] == ["Solitario"]  # interagisce solo con un estraneo
    assert {(r["subject"], r["object"]) for r in k["gene_condition"]} == {
        ("GENEX", "essential hypertension"), ("GENEX", "Migraine")}
    assert [(r["subject"], r["object"], r["n"]) for r in k["pathway"]] == [("Via comune", "GENEP, GENEX", 2)]


def test_clinvar_senza_alt(tmp_path, monkeypatch):
    g, _ = _setup(tmp_path, monkeypatch)
    g.annotate()
    k = _kinds(tmp_path)
    assert not [r for r in k["gene_condition"] if r["subject"] == "GENER"]
    assert sorted(r["subject"] for r in k["clinvar_unresolved"]) == ["GENER", "GENEU"]


def test_report_grafo_e_determinismo(tmp_path, monkeypatch):
    g, _ = _setup(tmp_path, monkeypatch)
    import dna_report
    g.annotate()
    a = dna_report.report_graph().read_text()
    g.annotate()
    assert a == dna_report.report_graph().read_text()
    assert a.startswith("# I tuoi farmaci e i tuoi geni nel grafo")
    assert "non aggiornato" not in a
    assert "| Farmacone | enzima | GENEX | rs1000002 AG" in a
    assert "Farmacone ↔ Secondo" in a
    assert "DrugCentral elenca «severe hypertension» tra le controindicazioni generali di Farmacone." in a
    assert "SIDER riporta «Headache» tra gli effetti segnalati di Secondo." in a
    assert "Introvabile" in a and "Malattia Inventata" in a and "Solitario" in a
    assert "- *Farmacone, altri geni:* RECETTORE" in a
    assert "Geni: GENER, GENEU" in a
    assert "| Via comune | GENEP, GENEX | 2 |" in a


def test_report_stantio(tmp_path, monkeypatch):
    g, _ = _setup(tmp_path, monkeypatch)
    import dna_report
    g.annotate()
    cfg = dict(CONFIG, graph=dict(CONFIG["graph"], drugs=["Secondo"]))
    (tmp_path / "config" / "genomics.json").write_text(json.dumps(cfg))
    assert "Report non aggiornato" in dna_report.report_graph().read_text()


def test_config_assente(tmp_path, monkeypatch):
    g, _ = _setup(tmp_path, monkeypatch, config=None)
    import dna_report
    g.annotate()
    k = _kinds(tmp_path)
    assert "drug_gene" not in k and k["config_missing"][0]["subject"] == "config/genomics.json"
    assert "non vuol dire nessuna interazione" in dna_report.report_graph().read_text()


@pytest.mark.parametrize("bad, msg", [
    ("{non json", "non è un JSON"),
    ('{"graph": null}', "manca la chiave"),
    ('{"graph": {"drugs": "Farmacone"}}', "lista di nomi"),
])
def test_config_malformato(tmp_path, monkeypatch, bad, msg):
    g, _ = _setup(tmp_path, monkeypatch, config=bad)
    with pytest.raises(SystemExit, match=msg):
        g.annotate()


def test_cerca_nomi(tmp_path, monkeypatch):
    g, _ = _setup(tmp_path, monkeypatch)
    assert g.find_drug("farm") == ["Farmacone"]
    assert g.find_condition("hypertension") == ["disease: essential hypertension", "disease: severe hypertension"]


def test_senza_grafo_caricato(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_graph
    with pytest.raises(SystemExit, match="dna_graph.py load"):
        dna_graph.annotate()
