"""PrimeKG accanto al DNA: i farmaci e i geni dell'utente dentro un grafo biomedico pubblico.

PrimeKG (Chandak, Huang, Zitnik — Scientific Data 2023, Harvard Dataverse doi:10.7910/DVN/IXA7BM) unisce
venti basi di conoscenza: malattie (MONDO), fenotipi (HPO), geni e proteine, vie (Reactome), farmaci con
bersagli, enzimi, trasportatori e interazioni (DrugBank), indicazioni e controindicazioni (DrugCentral),
effetti segnalati (SIDER). Le relazioni DrugBank hanno licenza non commerciale: il plugin distribuisce solo
questo script, i dati li scarica l'utente in data/dna/db/ (fuori da git; ~1,4 GB tra CSV e database).

    dna_graph.py load [--update-db] [--csv <kg.csv>]   # scarica kg.csv e carica data/dna/db/primekg.db
    dna_graph.py annotate                               # incrocia con i farmaci e i geni dell'utente
    dna_graph.py drug <testo>                           # i nomi dei farmaci che il grafo conosce
    dna_graph.py condition <testo>                      # i nomi di malattie e fenotipi

Cosa incrocia (config/genomics.json del repo dati, chiave "graph"):
- "drugs": i farmaci e gli integratori in uso, coi nomi DrugBank in inglese (per esempio Warfarin,
  Simvastatin): il genetista li ricava dal profilo, lo script non indovina le traduzioni;
- "conditions": i nomi esatti (maiuscole a parte) di malattie e fenotipi del quadro (per esempio
  hypertension, Migraine), scelti con `condition`: una parola generica come «anemia» tirerebbe dentro
  sindromi rare che non c'entrano.
I geni sono quelli che le annotazioni già segnalano: pannelli a rilevanza alta o media, varianti ClinVar
portate (patogeniche, protettive, risposta ai farmaci, fattore di rischio), PharmGKB.
Un collegamento del grafo è un'associazione da database e letteratura, non un rischio personale.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_common

PRIMEKG_URL = "https://dataverse.harvard.edu/api/access/datafile/6180620"
KEEP = {"drug_protein", "drug_drug", "contraindication", "indication", "off-label use", "drug_effect",
        "disease_protein", "phenotype_protein", "pathway_protein"}
DRUG_CONDITION = ("contraindication", "indication", "off-label use", "drug_effect")
CLINVAR_NOTABLE = ("athogenic", "rotective", "drug_response", "risk_factor")
INPUT_TABLES = ("annotations_panels", "annotations_clinvar", "annotations_pharmgkb")
COLUMNS = ["kind", "subject", "relation", "object", "variants", "n"]


def graph_db() -> Path:
    return dna_common.dna_dir() / "db" / "primekg.db"


def config_path() -> Path:
    return dna_common.data_root() / "config" / "genomics.json"


def _csv_cache(update: bool) -> Path:
    dest = dna_common.dna_dir() / "db" / "primekg_kg.csv"
    if dest.exists() and not update:
        return dest
    import dna_annotate
    path, _ = dna_annotate._download_atomic(PRIMEKG_URL, dest, "PrimeKG (~1 GB)")
    return path


def load(update: bool = False, csv_path: Path | None = None) -> int:
    """Carica le sole relazioni utili in un sqlite a parte, costruito su .part e rinominato a fine lavoro."""
    src = Path(csv_path) if csv_path else _csv_cache(update)
    db = graph_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(db.name + ".part")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE edges(relation TEXT, role TEXT, x_type TEXT, x_name TEXT, y_type TEXT, y_name TEXT)")
    with open(src, newline="", encoding="utf-8") as fh:
        con.executemany("INSERT INTO edges VALUES(?,?,?,?,?,?)",
                        ((r["relation"], r["display_relation"], r["x_type"], r["x_name"], r["y_type"], r["y_name"])
                         for r in csv.DictReader(fh) if r["relation"] in KEEP))
    con.execute("CREATE INDEX ix_x ON edges(x_name COLLATE NOCASE, x_type)")
    con.execute("CREATE INDEX ix_y ON edges(y_name COLLATE NOCASE, y_type)")
    n = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    con.commit()
    con.close()
    tmp.replace(db)
    v = dna_common.load_versions()
    v["primekg"] = f"Dataverse IXA7BM, sha256 {dna_common.file_sha256(src)[:12]}"
    dna_common.save_versions(v)
    return n


def _graph() -> sqlite3.Connection:
    if not graph_db().exists():
        raise SystemExit("PrimeKG non caricato: esegui prima `dna_graph.py load` (~1 GB da Harvard Dataverse).")
    return sqlite3.connect(graph_db())


def _neighbors(con, name: str, ntype: str, relations) -> set[tuple[str, str, str, str]]:
    """(relation, role, tipo, nome) dei vicini di un nodo, da qualunque lato stia l'arco."""
    q = ",".join("?" * len(relations))
    out = set()
    for side, other in (("x", "y"), ("y", "x")):
        out |= set(con.execute(
            f"SELECT relation, role, {other}_type, {other}_name FROM edges "
            f"WHERE {side}_name = ? COLLATE NOCASE AND {side}_type = ? AND relation IN ({q})",
            (name, ntype, *relations)))
    return out


def _canonical(con, name: str, types: tuple[str, ...]) -> str | None:
    q = ",".join("?" * len(types))
    for side in ("x", "y"):
        row = con.execute(f"SELECT {side}_name FROM edges WHERE {side}_type IN ({q}) "
                          f"AND {side}_name = ? COLLATE NOCASE LIMIT 1", (*types, name)).fetchone()
        if row:
            return row[0]
    return None


def _config() -> dict | None:
    """None se il config manca; SystemExit leggibile se è scritto male."""
    p = config_path()
    if not p.exists():
        return None
    try:
        g = json.loads(p.read_text(encoding="utf-8")).get("graph")
    except (json.JSONDecodeError, AttributeError) as e:
        raise SystemExit(f"{p}: non è un JSON con un oggetto in cima ({e}).")
    if not isinstance(g, dict):
        raise SystemExit(f"{p}: manca la chiave \"graph\" con dentro \"drugs\" e \"conditions\".")
    out = {}
    for key in ("drugs", "conditions"):
        val = g.get(key, [])
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise SystemExit(f"{p}: \"graph.{key}\" deve essere una lista di nomi, per esempio [\"Warfarin\"].")
        out[key] = [x.strip() for x in val if x.strip()]
    return out


def _tables(gcon) -> set[str]:
    return {r[0] for r in gcon.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def inputs_fingerprint() -> str:
    """Impronta di ciò da cui dipende annotations_graph: config, annotazioni di partenza, versione del grafo."""
    h = hashlib.sha256()
    p = config_path()
    h.update(p.read_bytes() if p.exists() else b"-")
    gcon = dna_common.connect()
    have = _tables(gcon)
    for t in INPUT_TABLES:
        h.update(t.encode())
        if t in have:
            for row in gcon.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3"):
                h.update(repr(row).encode())
    h.update(str(dna_common.load_versions().get("primekg")).encode())
    return h.hexdigest()


def personal_genes() -> tuple[dict[str, list[str]], set[str], list[tuple[str, str]]]:
    """Le varianti rilevanti per gene, i geni notevoli e i record ClinVar non valutabili (gene, descrizione)."""
    gcon = dna_common.connect()
    have = _tables(gcon)
    by_gene: dict[str, list[str]] = {}
    unresolved: list[tuple[str, str]] = []
    if "annotations_panels" in have:
        for gene, rsid, gt, label, rel in gcon.execute(
                "SELECT gene, rsid, genotype, label, relevance FROM annotations_panels "
                "WHERE relevance IN ('alta', 'media')"):
            by_gene.setdefault(gene, []).append(f"{rsid} {gt} — pannello: {label}, rilevanza {rel}")
    if "annotations_clinvar" in have:
        # ALT "." vuol dire che il record non dice quale allele asserisce: niente deduzioni dagli altri record
        # dello stesso rsid (su GRCh37 il riferimento è a volte proprio l'allele raro, come per rs6025).
        for gene, rsid, gt, sig, alt in gcon.execute(
                "SELECT gene, rsid, genotype, clnsig, alt FROM annotations_clinvar"):
            if not any(k in sig for k in CLINVAR_NOTABLE) or "onflicting" in sig or gene in ("", "n/d"):
                continue
            if set(gt) & {"D", "I", "-"}:
                continue
            desc = f"{rsid} {gt} — ClinVar: {sig.replace('_', ' ')}"
            if alt in (".", ""):
                unresolved.append((gene, desc))
            elif set(gt) & set(alt.split(",")):
                by_gene.setdefault(gene, []).append(desc)
    if "annotations_pharmgkb" in have:
        for gene, rsid, gt, level, drugs in gcon.execute(
                "SELECT gene, rsid, genotype, level, drugs FROM annotations_pharmgkb"):
            for g in filter(None, (x.strip() for x in gene.replace(";", ",").split(","))):
                by_gene.setdefault(g, []).append(f"{rsid} {gt} — PharmGKB {level}: {drugs}")
    variants = {g: sorted(set(v)) for g, v in by_gene.items()}
    return variants, set(variants), sorted(set(unresolved))


def annotate() -> int:
    con = _graph()
    cfg = _config()
    variants, notable, unresolved = personal_genes()
    rows: list[dict] = []

    def add(kind, subject="", relation="", obj="", var="", n=None):
        rows.append({"kind": kind, "subject": subject, "relation": relation, "object": obj,
                     "variants": var, "n": n})

    if cfg is None:
        add("config_missing", str(config_path().relative_to(dna_common.data_root())))
        cfg = {"drugs": [], "conditions": []}
    conditions = set()
    for name in cfg["conditions"]:
        canon = _canonical(con, name, ("disease", "effect/phenotype"))
        if canon is None:
            add("condition_missing", name)
        else:
            conditions.add(canon.lower())
    drugs = []
    for name in cfg["drugs"]:
        canon = _canonical(con, name, ("drug",))
        if canon is None:
            add("drug_missing", name)
        else:
            drugs.append(canon)
    for d in drugs:
        found = 0
        for rel, role, otype, other in _neighbors(con, d, "drug", ("drug_protein",)):
            add("drug_gene", d, role, other, "; ".join(variants.get(other, [])))
            found += 1
        for rel, role, otype, other in _neighbors(con, d, "drug", DRUG_CONDITION):
            if other.lower() in conditions:
                add("drug_condition", d, rel, other)
                found += 1
        for rel, role, otype, other in _neighbors(con, d, "drug", ("drug_drug",)):
            if other in drugs:
                found += 1
                if d < other:
                    add("drug_drug", d, role, other)
        if not found:
            add("drug_nolinks", d)
    pathways: dict[str, set[str]] = {}
    for gene in sorted(notable):
        for rel, role, otype, other in _neighbors(con, gene, "gene/protein", ("disease_protein", "phenotype_protein")):
            if other.lower() in conditions:
                add("gene_condition", gene, otype, other, "; ".join(variants.get(gene, [])))
        for rel, role, otype, other in _neighbors(con, gene, "gene/protein", ("pathway_protein",)):
            pathways.setdefault(other, set()).add(gene)
    for pw, genes in pathways.items():
        if len(genes) >= 2:
            add("pathway", pw, "", ", ".join(sorted(genes)), n=len(genes))
    if not notable:
        add("genes_missing")
    for gene, desc in unresolved:
        add("clinvar_unresolved", gene, "", desc)

    rows = [json.loads(r) for r in sorted({json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows})]
    out = dna_common.dna_dir() / "annotated" / "graph.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows))
    gcon = dna_common.connect()
    gcon.execute("DROP TABLE IF EXISTS annotations_graph")
    gcon.execute(f"CREATE TABLE annotations_graph({','.join(COLUMNS)})")
    gcon.executemany(f"INSERT INTO annotations_graph VALUES({','.join('?' * len(COLUMNS))})",
                     [[r[c] for c in COLUMNS] for r in rows])
    gcon.commit()
    dna_common.set_meta(gcon, "graph_inputs", inputs_fingerprint())
    return len(rows)


def find_drug(text: str) -> list[str]:
    con = _graph()
    like = f"%{text}%"
    return [r[0] for r in con.execute(
        "SELECT x_name FROM edges WHERE x_type='drug' AND x_name LIKE ?1 "
        "UNION SELECT y_name FROM edges WHERE y_type='drug' AND y_name LIKE ?1 ORDER BY 1 LIMIT 30", (like,))]


def find_condition(text: str) -> list[str]:
    con = _graph()
    like = f"%{text}%"
    return [f"{t}: {n}" for t, n in con.execute(
        "SELECT t, n FROM (SELECT x_type t, x_name n FROM edges WHERE x_name LIKE ?1 "
        "UNION SELECT y_type, y_name FROM edges WHERE y_name LIKE ?1) "
        "WHERE t IN ('disease','effect/phenotype') ORDER BY t, n LIMIT 60", (like,))]


def main() -> None:
    p = argparse.ArgumentParser(description="PrimeKG accanto al DNA")
    sub = p.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("load")
    lp.add_argument("--update-db", action="store_true")
    lp.add_argument("--csv")
    sub.add_parser("annotate")
    dp = sub.add_parser("drug")
    dp.add_argument("text")
    cp = sub.add_parser("condition")
    cp.add_argument("text")
    a = p.parse_args()
    if a.cmd == "load":
        print(f"PrimeKG: {load(a.update_db, Path(a.csv) if a.csv else None)} relazioni caricate in {graph_db()}")
    elif a.cmd == "annotate":
        print(f"graph: {annotate()} annotazioni")
    elif a.cmd == "drug":
        print("\n".join(find_drug(a.text)) or "nessun farmaco con quel nome nel grafo")
    else:
        print("\n".join(find_condition(a.text)) or "nessuna malattia o fenotipo con quel nome nel grafo")


if __name__ == "__main__":
    main()
