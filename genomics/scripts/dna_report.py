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
            out.append(f"| {gene} | {rsid} | {gt} | {eff} | {RILEVANZA_ICONA.get(rel, rel)} |")
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
        "SELECT rsid, genotype, clnsig, condition, gene FROM annotations_clinvar "
        "WHERE clnsig LIKE '%athogenic%' OR clnsig LIKE '%rotective%' "
        "ORDER BY gene, rsid").fetchall()
    if not rows:
        out.append("Nessuna variante patogenica/protettiva nota trovata nel raw.")
    else:
        out += ["| Gene | SNP | Genotipo | Significato | Condizione |",
                "|------|-----|----------|-------------|------------|"]
        out += [f"| {g} | {r} | {gt} | {s} | {c.replace('_', ' ')} |"
                for r, gt, s, c, g in rows]
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
    out += [f"| {g} | {r} | {gt} | {lv} | {d} | {cat} |"
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
        out += [f"| {r} | {gt} | {g} | {p} | {e} | {s} |"
                for r, gt, g, p, e, s in con.execute(
                    "SELECT rsid, genotype, gene, p_value, effect, study "
                    "FROM annotations_gwas WHERE trait=? ORDER BY rsid", (t,))]
        out.append("")
    out.append(_fonti())
    dest = _reports_dir() / "gwas.md"
    dest.write_text("\n".join(out))
    return dest


REPORTS = {"panels": report_panels, "clinvar": report_clinvar,
           "pharmgkb": report_pharmgkb, "gwas": report_gwas}


def main() -> None:
    p = argparse.ArgumentParser(description="Report DNA per strato")
    p.add_argument("--layer", choices=sorted(REPORTS), action="append")
    args = p.parse_args()
    con = dna_common.connect()
    present = {r[0].replace("annotations_", "") for r in con.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'annotations_%'")}
    for layer in (args.layer or sorted(present)):
        if layer not in present:
            print(f"{layer}: nessuna annotazione (esegui prima dna_annotate) — salto")
            continue
        print(f"scritto: {REPORTS[layer]()}")


if __name__ == "__main__":
    main()
