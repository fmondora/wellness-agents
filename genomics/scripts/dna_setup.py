"""Bootstrap one-shot della pipeline DNA: ingest → panels (+ opzionale clinvar/gwas) → report.

Pensato per l'intake del genetista: appena l'utente fornisce il raw (23andMe o altro),
questo script sistema da solo il database, senza altri comandi manuali.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_annotate
import dna_common
import dna_ingest
import dna_report


def bootstrap(raw_file: Path, with_external: bool = False,
              panels_dir: Path = dna_annotate.DEFAULT_PANELS,
              build: str = "GRCh37") -> dict:
    result: dict = {"ingested": 0, "layers": {}, "reports": [], "errors": []}

    ingest_res = dna_ingest.ingest(Path(raw_file), build)
    if ingest_res["status"] == "already_ingested":
        print(f"Raw già ingestito in precedenza: {raw_file}")
    else:
        print(f"Ingest: {ingest_res['inserted']} genotipi inseriti "
              f"({ingest_res['skipped_nocall']} no-call scartati)")
    result["ingested"] = ingest_res["inserted"]

    n_panels = dna_annotate.annotate_panels(Path(panels_dir))
    print(f"Pannelli: {n_panels} annotazioni")
    result["layers"]["panels"] = n_panels

    if with_external:
        try:
            n_clinvar = dna_annotate.annotate_clinvar(update=False)
            print(f"ClinVar: {n_clinvar} annotazioni")
            result["layers"]["clinvar"] = n_clinvar
        except SystemExit as e:
            msg = f"ClinVar fallito: {e}"
            print(msg)
            result["errors"].append(msg)
        try:
            n_gwas = dna_annotate.annotate_gwas(update=False)
            print(f"GWAS: {n_gwas} annotazioni")
            result["layers"]["gwas"] = n_gwas
        except SystemExit as e:
            msg = f"GWAS fallito: {e}"
            print(msg)
            result["errors"].append(msg)

    con = dna_common.connect()
    present = {r[0].replace("annotations_", "") for r in con.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'annotations_%'")}
    for layer in sorted(present):
        dest = dna_report.REPORTS[layer]()
        print(f"Report: {dest}")
        result["reports"].append(str(dest))

    print("\n--- Riepilogo ---")
    for layer, n in result["layers"].items():
        print(f"  {layer}: {n} righe")
    for r in result["reports"]:
        print(f"  report: {r}")
    print("\nProssimi passi:")
    if "pharmgkb" not in present:
        print("  - PharmGKB (farmacogenomica) resta manuale: scarica "
              "'clinicalAnnotations.zip' da https://www.pharmgkb.org/downloads "
              "ed estrai clinical_annotations.tsv in data/dna/db/pharmgkb/, "
              "poi `dna_annotate.py --layer pharmgkb`")
    if not with_external:
        print("  - Strati esterni (ClinVar+GWAS, ~1GB) non scaricati: rilancia con "
              "--with-external per includerli")
    if result["errors"]:
        print("  - Errori da rivedere: " + "; ".join(result["errors"]))

    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Bootstrap one-shot della pipeline DNA")
    p.add_argument("raw_file")
    p.add_argument("--with-external", action="store_true",
                   help="Scarica/usa cache di ClinVar e GWAS Catalog (~1GB)")
    p.add_argument("--panels-dir", default=str(dna_annotate.DEFAULT_PANELS))
    p.add_argument("--build", default="GRCh37")
    args = p.parse_args()
    bootstrap(Path(args.raw_file), with_external=args.with_external,
              panels_dir=Path(args.panels_dir), build=args.build)


if __name__ == "__main__":
    main()
