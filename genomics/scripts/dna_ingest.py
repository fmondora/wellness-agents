"""Ingest raw genotipi (txt 23andMe) → data/dna/genotypes.db. Deterministico e idempotente."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_common

NO_CALLS = {"--", ""}


def _rows_txt(path: Path):
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        rsid, chrom, pos, gt = parts
        yield rsid, chrom, int(pos), gt.strip()


def ingest(path: Path, build: str = "GRCh37") -> dict:
    path = Path(path)
    con = dna_common.connect()
    digest = dna_common.file_sha256(path)
    if dna_common.get_meta(con, f"ingested:{digest}"):
        return {"status": "already_ingested", "inserted": 0, "skipped_nocall": 0}
    inserted = skipped = 0
    for rsid, chrom, pos, gt in _rows_txt(path):
        if gt in NO_CALLS:
            skipped += 1
            continue
        con.execute(
            "INSERT INTO genotypes(rsid,chrom,pos,genotype,source_file,build) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(rsid) DO UPDATE SET "
            "genotype=excluded.genotype, source_file=excluded.source_file",
            (rsid, chrom, pos, gt, path.name, build))
        inserted += 1
    dna_common.set_meta(con, "build", build)
    dna_common.set_meta(con, f"ingested:{digest}", path.name)
    con.commit()
    return {"status": "ok", "inserted": inserted, "skipped_nocall": skipped}


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest raw DNA nel repo dati")
    p.add_argument("file")
    p.add_argument("--build", default="GRCh37")
    args = p.parse_args()
    res = ingest(Path(args.file), args.build)
    print(res)


if __name__ == "__main__":
    main()
