"""Report leggibili dagli strati annotati. Deterministici: solo db + versioni."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_common

DISCLAIMER_CLINICO = (
    "> ⚠️ **Dati da chip array: falsi positivi noti.** Ogni variante patogenica "
    "va confermata con sequenziamento clinico e valutata con un genetista medico. "
    "Questo report non è una diagnosi.")

RILEVANZA_ICONA = {"alta": "⚠️ Alta", "media": "⚠️ Media", "bassa": "ℹ️ Bassa",
                   "neutro": "✅ Neutro", "da_rivedere": "❓ Da rivedere"}


def _md(v) -> str:
    """Escape del pipe per non spezzare le tabelle markdown (es. CLNDN multi-condizione)."""
    return str(v).replace("|", "\\|")


def _reports_dir() -> Path:
    p = dna_common.dna_dir() / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fonti() -> str:
    con = dna_common.connect()
    v = dna_common.load_versions()
    lines = ["## Fonti", "",
             f"- Build: {dna_common.get_meta(con, 'build')}",
             f"- SNP nel raw: {con.execute('SELECT COUNT(*) FROM genotypes').fetchone()[0]}"]
    lines += [f"- {k}: release {val}" for k, val in sorted(v.items())]
    lines.append("- Pannelli: plugin genomics (wellness-agents)")
    return "\n".join(lines) + "\n"


def report_panels() -> Path:
    con = dna_common.connect()
    out = ["# Genomica — Profilo SNP", "",
           "*Generato da dna_report.py — non modificare a mano: rigenerare.*", ""]
    pathways = [r[0] for r in con.execute(
        "SELECT DISTINCT pathway FROM annotations_panels ORDER BY pathway")]
    for pw in pathways:
        out += [f"## {pw}", "", "| Gene | SNP | Genotipo | Effetto | Rilevanza |",
                "|------|-----|----------|---------|-----------|"]
        for gene, rsid, gt, eff, rel in con.execute(
                "SELECT gene, rsid, genotype, effect, relevance FROM annotations_panels "
                "WHERE pathway=? ORDER BY gene, rsid", (pw,)):
            out.append(f"| {_md(gene)} | {_md(rsid)} | {_md(gt)} | {_md(eff)} | "
                       f"{RILEVANZA_ICONA.get(rel, rel)} |")
        out.append("")
    out.append(_fonti())
    dest = dna_common.data_root() / "kb" / "genomica.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out))
    return dest


def report_clinvar() -> Path:
    con = dna_common.connect()
    out = ["# Report ClinVar", "", DISCLAIMER_CLINICO, ""]
    rows = con.execute(
        "SELECT rsid, genotype, clnsig, condition, gene, ref, alt FROM annotations_clinvar "
        "WHERE (clnsig LIKE '%athogenic%' OR clnsig LIKE '%rotective%') "
        "AND clnsig NOT LIKE '%onflicting%' "
        "ORDER BY gene, rsid").fetchall()
    portatori, non_portatore, non_valutabili = [], 0, 0
    for r, gt, s, c, g, ref, alt in rows:
        alleles_alt = set(alt.split(","))
        gt_chars = set(gt)
        if gt_chars & {"D", "I"}:
            non_valutabili += 1
            continue
        if gt_chars & alleles_alt:
            zigosita = ("omozigote variante" if all(ch in alleles_alt for ch in gt)
                        else "eterozigote")
            portatori.append((r, gt, s, c, g, zigosita))
        else:
            non_portatore += 1
    if not portatori:
        out.append("Nessuna variante patogenica/protettiva portata trovata nel raw.")
    else:
        out += ["| Gene | SNP | Genotipo | Zigosità | Significato | Condizione |",
                "|------|-----|----------|----------|-------------|------------|"]
        out += [f"| {_md(g)} | {_md(r)} | {_md(gt)} | {_md(z)} | {_md(s)} | "
                f"{_md(c.replace('_', ' '))} |"
                for r, gt, s, c, g, z in portatori]
    if non_portatore:
        out.append(f"\n*Escluse {non_portatore} posizioni patogeniche note dove il genotipo "
                   "è omozigote riferimento (allele di rischio assente).*")
    if non_valutabili:
        out.append(f"\n*{non_valutabili} varianti non valutabili (indel da chip).*")
    out += ["", _fonti()]
    dest = _reports_dir() / "clinvar.md"
    dest.write_text("\n".join(out))
    return dest


def report_pharmgkb() -> Path:
    con = dna_common.connect()
    out = ["# Report Farmacogenomica (PharmGKB)", "",
           "> Da discutere sempre con il medico che prescrive. Nessuna decisione "
           "su farmaci nasce da questo report.", "",
           "| Gene | SNP | Genotipo | Livello | Farmaci | Categoria |",
           "|------|-----|----------|---------|---------|-----------|"]
    out += [f"| {_md(g)} | {_md(r)} | {_md(gt)} | {_md(lv)} | {_md(d)} | {_md(cat)} |"
            for r, gt, g, lv, d, cat in con.execute(
                "SELECT rsid, genotype, gene, level, drugs, category "
                "FROM annotations_pharmgkb ORDER BY level, gene, rsid")]
    out += ["", _fonti()]
    dest = _reports_dir() / "pharmgkb.md"
    dest.write_text("\n".join(out))
    return dest


def report_gwas() -> Path:
    con = dna_common.connect()
    out = ["# Report GWAS Catalog", "",
           "> Associazioni statistiche da studi di popolazione: effect size "
           "tipicamente piccoli. Predisposizione ≠ destino.", ""]
    traits = [r[0] for r in con.execute(
        "SELECT DISTINCT trait FROM annotations_gwas ORDER BY trait")]
    for t in traits:
        out += [f"## {t}", "", "| SNP | Genotipo | Gene | p-value | OR/beta | Studio |",
                "|-----|----------|------|---------|---------|--------|"]
        out += [f"| {_md(r)} | {_md(gt)} | {_md(g)} | {_md(p)} | {_md(e)} | {_md(s)} |"
                for r, gt, g, p, e, s in con.execute(
                    "SELECT rsid, genotype, gene, p_value, effect, study "
                    "FROM annotations_gwas WHERE trait=? ORDER BY rsid", (t,))]
        out.append("")
    out.append(_fonti())
    dest = _reports_dir() / "gwas.md"
    dest.write_text("\n".join(out))
    return dest


RUOLO = {"target": "bersaglio", "enzyme": "enzima", "transporter": "trasportatore",
         "carrier": "carrier (DrugBank)"}
FRASE_FARMACO = {
    "contraindication": "DrugCentral elenca «{o}» tra le controindicazioni generali di {s}",
    "indication": "DrugCentral elenca «{o}» tra le indicazioni di {s}",
    "off-label use": "DrugCentral elenca «{o}» tra gli usi off-label di {s}",
    "drug_effect": "SIDER riporta «{o}» tra gli effetti segnalati di {s}",
}
TIPO = {"disease": "malattia", "effect/phenotype": "fenotipo"}


def report_graph() -> Path:
    import dna_graph
    con = dna_common.connect()
    rows = con.execute("SELECT kind, subject, relation, object, variants, n FROM annotations_graph "
                       "ORDER BY kind, subject, relation, object").fetchall()
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r[1:])
    out = ["# I tuoi farmaci e i tuoi geni nel grafo (PrimeKG)", ""]
    if dna_common.get_meta(con, "graph_inputs") != dna_graph.inputs_fingerprint():
        out += ["> ⚠️ **Report non aggiornato:** il config o le annotazioni sono cambiati dall'ultimo incrocio. "
                "Rilancia `dna_graph.py annotate`, poi questo report.", ""]
    out += ["> Ogni riga è un'associazione da database e letteratura (DrugBank, DrugCentral, SIDER, MONDO, HPO, "
            "Reactome), non un rischio personale né una spiegazione di un sintomo. Le righe servono a fare domande "
            "migliori al medico che prescrive o al farmacista; nessuna decisione su farmaci nasce da qui.", ""]
    if by.get("config_missing"):
        out += [f"*Farmaci e condizioni non configurati ({by['config_missing'][0][0]}, chiave \"graph\"): "
                "il report mostra solo i geni e le vie. Nessuna riga sui farmaci non vuol dire nessuna "
                "interazione.*", ""]
    if by.get("drug_missing"):
        out += ["*Non trovati nel grafo, controlla il nome DrugBank in `config/genomics.json`: "
                + ", ".join(s for s, *_ in by["drug_missing"]) + ".*", ""]
    if by.get("condition_missing"):
        out += ["*Condizioni non trovate nel grafo, controlla il nome con `dna_graph.py condition`: "
                + ", ".join(s for s, *_ in by["condition_missing"]) + ".*", ""]
    if by.get("drug_nolinks"):
        out += ["*Trovati nel grafo, ma senza bersagli, interazioni con gli altri farmaci in uso o legami col "
                "quadro: " + ", ".join(s for s, *_ in by["drug_nolinks"]) + ".*", ""]
    drug_gene = by.get("drug_gene", [])
    if drug_gene:
        out += ["## I tuoi farmaci: bersagli ed enzimi", "",
                "Nella tabella, i geni del farmaco su cui le annotazioni segnalano una tua variante (pannelli a "
                "rilevanza alta o media, ClinVar, PharmGKB). Sotto, gli altri geni del farmaco.", ""]
        with_var = sorted(r for r in drug_gene if r[3])
        if with_var:
            out += ["| Farmaco | Ruolo | Gene | Le tue varianti sul gene |", "|---|---|---|---|"]
            out += [f"| {_md(s)} | {RUOLO.get(rel, rel)} | {_md(o)} | {_md(v)} |" for s, rel, o, v, _ in with_var]
        else:
            out.append("Nessuna tua variante segnalata sui geni dei tuoi farmaci.")
        rest: dict[str, set[str]] = {}
        for s, rel, o, v, _ in drug_gene:
            if not v:
                rest.setdefault(s, set()).add(o)
        out.append("")
        out += [f"- *{_md(s)}, altri geni:* {', '.join(sorted(g))}" for s, g in sorted(rest.items())]
        out.append("")
    if by.get("drug_drug"):
        out += ["## Interazioni tra i tuoi farmaci", "",
                "DrugBank segnala un'interazione, senza dettaglio di gravità: da chiedere al farmacista.", ""]
        out += [f"- {_md(s)} ↔ {_md(o)}" for s, _, o, *_ in by["drug_drug"]] + [""]
    if by.get("drug_condition"):
        out += ["## Cosa dicono le basi dati dei tuoi farmaci sulle condizioni del tuo quadro", "",
                "Sono etichette generali del principio attivo, senza via, forma né dose: non dicono che il tuo "
                "farmaco ti sia controindicato o ti dia quell'effetto. Ogni riga è una domanda per il medico che "
                "lo prescrive.", ""]
        out += [f"- {FRASE_FARMACO.get(rel, '{s} → {o}').format(s=_md(s), o=_md(o))}."
                for s, rel, o, *_ in by["drug_condition"]]
        out.append("")
    if by.get("gene_condition"):
        out += ["## I tuoi geni e il tuo quadro", "",
                "Il collegamento è tra il gene e la condizione, non tra la tua variante e la condizione: "
                "l'ultima colonna dice per che cosa è annotata la variante, che può essere tutt'altro.", "",
                "| Gene | Il gene è associato a | Tipo | La tua variante, annotata per |", "|---|---|---|---|"]
        out += [f"| {_md(s)} | {_md(o)} | {TIPO.get(rel, rel)} | {_md(v)} |"
                for s, rel, o, v, _ in by["gene_condition"]]
        out.append("")
    if by.get("genes_missing"):
        out += ["*Nessun gene segnalato dalle annotazioni (pannelli alta/media, ClinVar portate, PharmGKB): "
                "la parte dei geni resta vuota.*", ""]
    if by.get("clinvar_unresolved"):
        genes = sorted({s for s, *_ in by["clinvar_unresolved"]})
        out += [f"*{len(by['clinvar_unresolved'])} annotazioni ClinVar notevoli senza allele alternativo nel "
                "database, quindi non valutabili come portate e fuori dall'incrocio. Geni: "
                + ", ".join(genes) + ". Da guardare una per una con `dna_query.py --gene`.*", ""]
    if by.get("pathway"):
        allp = sorted(by["pathway"], key=lambda r: (-r[4], r[0]))
        top = allp[:25]
        out += ["## Vie dove compaiono più tuoi geni", "",
                f"Le prime {len(top)} di {len(allp)} vie Reactome con almeno due geni segnalati. I pannelli sono "
                "costruiti per via, quindi una parte della convergenza viene da come sono scelti i geni: è un "
                "indice dove guardare, non una misura.", "",
                "| Via (Reactome) | Geni | Quanti |", "|---|---|---|"]
        out += [f"| {_md(s)} | {_md(o)} | {n} |" for s, _, o, _, n in top]
        out.append("")
    out.append(_fonti())
    dest = _reports_dir() / "grafo.md"
    dest.write_text("\n".join(out))
    return dest


REPORTS = {"panels": report_panels, "clinvar": report_clinvar,
           "pharmgkb": report_pharmgkb, "gwas": report_gwas, "graph": report_graph}


def main() -> None:
    p = argparse.ArgumentParser(description="Report DNA per strato")
    p.add_argument("--layer", choices=sorted(REPORTS), action="append")
    args = p.parse_args()
    con = dna_common.connect()
    present = {r[0].replace("annotations_", "") for r in con.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'annotations_%'")}
    for layer in (args.layer or sorted(present)):
        if layer not in present:
            cmd = "dna_graph.py annotate" if layer == "graph" else "dna_annotate.py"
            print(f"{layer}: nessuna annotazione (esegui prima {cmd}) — salto")
            continue
        print(f"scritto: {REPORTS[layer]()}")


if __name__ == "__main__":
    main()
