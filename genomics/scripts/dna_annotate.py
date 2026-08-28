"""Annotazione deterministica dei genotipi per strato. Output: jsonl + tabelle sqlite."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_common

DEFAULT_PANELS = Path(__file__).resolve().parent.parent / "knowledge" / "panels"

CLINVAR_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh37/clinvar.vcf.gz"


def _annotated_path(layer: str) -> Path:
    p = dna_common.dna_dir() / "annotated"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{layer}.jsonl"


def _write_layer(layer: str, rows: list[dict], columns: list[str]) -> int:
    rows = sorted(rows, key=lambda r: (r.get("panel", ""), r["rsid"]))
    with open(_annotated_path(layer), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    con = dna_common.connect()
    con.execute(f"DROP TABLE IF EXISTS annotations_{layer}")
    con.execute(f"CREATE TABLE annotations_{layer}({','.join(columns)})")
    for r in rows:
        con.execute(
            f"INSERT INTO annotations_{layer} VALUES({','.join('?' * len(columns))})",
            [r.get(c) for c in columns])
    con.commit()
    return len(rows)


def _genotypes() -> dict[str, str]:
    con = dna_common.connect()
    return dict(con.execute("SELECT rsid, genotype FROM genotypes"))


def annotate_panels(panels_dir: Path = DEFAULT_PANELS) -> int:
    gts = _genotypes()
    rows = []
    for pf in sorted(Path(panels_dir).glob("*.json")):
        panel = json.loads(pf.read_text())
        for snp in panel["snps"]:
            gt = gts.get(snp["rsid"])
            if gt is None:
                continue
            interp = snp["interpretations"].get(gt) or snp["interpretations"].get(gt[::-1])
            if interp is None:
                interp = {"effect": f"genotipo {gt} non in tabella interpretazioni",
                          "relevance": "da_rivedere"}
            rows.append({"rsid": snp["rsid"], "genotype": gt, "panel": panel["panel"],
                         "pathway": panel["pathway"], "gene": snp["gene"],
                         "label": snp["label"], "effect": interp["effect"],
                         "relevance": interp["relevance"],
                         "source": f"panel:{pf.name}", "db_version": "plugin"})
    return _write_layer("panels", rows,
                        ["rsid", "genotype", "panel", "pathway", "gene",
                         "label", "effect", "relevance"])


def _require_build(expected: str = "GRCh37") -> None:
    con = dna_common.connect()
    build = dna_common.get_meta(con, "build")
    if build != expected:
        raise SystemExit(
            f"Build del raw = {build}, il DB è {expected}: mai mescolare build.")


def _info_field(info: str, key: str) -> str | None:
    for part in info.split(";"):
        if part.startswith(key + "="):
            return part.split("=", 1)[1]
    return None


def _clinvar_cache(update: bool) -> Path:
    dest = dna_common.dna_dir() / "db" / "clinvar_GRCh37.vcf.gz"
    if dest.exists() and not update:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Scarico ClinVar GRCh37 (~250MB) da {CLINVAR_URL} ...")
    try:
        urllib.request.urlretrieve(CLINVAR_URL, dest)
    except Exception as e:
        if dest.exists():
            print(f"Download fallito ({e}): uso la cache esistente.")
            return dest
        raise SystemExit(f"Download ClinVar fallito e nessuna cache: {e}")
    return dest


def annotate_clinvar(update: bool = False, vcf_path: Path | None = None) -> int:
    _require_build("GRCh37")
    gts = _genotypes()
    path = vcf_path or _clinvar_cache(update)
    rows, file_date = [], "sconosciuta"
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("##fileDate="):
                file_date = line.strip().split("=", 1)[1]
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 8:
                continue
            info = f[7]
            rs = _info_field(info, "RS")
            rsid = f"rs{rs}" if rs else (f[2] if f[2].startswith("rs") else None)
            if rsid is None or rsid not in gts:
                continue
            rows.append({"rsid": rsid, "genotype": gts[rsid],
                         "clnsig": _info_field(info, "CLNSIG") or "n/d",
                         "condition": _info_field(info, "CLNDN") or "n/d",
                         "gene": (_info_field(info, "GENEINFO") or ":").split(":")[0],
                         "source": "clinvar", "db_version": file_date})
    versions = dna_common.load_versions()
    versions["clinvar"] = file_date
    dna_common.save_versions(versions)
    return _write_layer("clinvar", rows,
                        ["rsid", "genotype", "clnsig", "condition", "gene"])


def main() -> None:
    p = argparse.ArgumentParser(description="Annotazione DNA per strato")
    p.add_argument("--layer", required=True,
                   choices=["panels", "clinvar", "gwas", "pharmgkb"])
    p.add_argument("--panels-dir", default=str(DEFAULT_PANELS))
    p.add_argument("--update-db", action="store_true")
    args = p.parse_args()
    if args.layer == "panels":
        n = annotate_panels(Path(args.panels_dir))
    elif args.layer == "clinvar":
        n = annotate_clinvar(update=args.update_db)   # Task 5
    elif args.layer == "gwas":
        n = annotate_gwas(update=args.update_db)       # Task 6
    else:
        n = annotate_pharmgkb()                        # Task 7
    print(f"{args.layer}: {n} annotazioni")


if __name__ == "__main__":
    main()
