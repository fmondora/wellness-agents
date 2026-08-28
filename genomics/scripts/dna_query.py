"""Lookup rsID/gene su genotipi + tutte le annotazioni."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_common


def _layers(con) -> list[str]:
    # Save and reset row_factory to get tuples for this query
    orig_factory = con.row_factory
    con.row_factory = None
    try:
        result = [r[0].replace("annotations_", "") for r in con.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'annotations_%'")]
    finally:
        con.row_factory = orig_factory
    return result


def lookup(rsid: str | None = None, gene: str | None = None) -> dict:
    con = dna_common.connect()
    con.row_factory = lambda cur, row: {
        d[0]: row[i] for i, d in enumerate(cur.description)}
    result = {"genotype": None, "annotations": []}
    if rsid:
        row = con.execute("SELECT genotype FROM genotypes WHERE rsid=?", (rsid,)).fetchone()
        result["genotype"] = row["genotype"] if row else None
    for layer in _layers(con):
        where, arg = ("rsid=?", rsid) if rsid else ("gene=?", gene)
        for r in con.execute(f"SELECT * FROM annotations_{layer} WHERE {where}", (arg,)):
            r["layer"] = layer
            result["annotations"].append(r)
    return result


def _web(rsid: str) -> None:
    print(f"\nScheda pubblica: https://www.ncbi.nlm.nih.gov/snp/{rsid}")
    try:
        with urllib.request.urlopen(
                f"https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/{rsid[2:]}",
                timeout=10) as resp:
            data = json.load(resp)
        print(f"dbSNP: {len(data.get('primary_snapshot_data', {}).get('allele_annotations', []))} annotazioni alleliche")
    except Exception as e:
        print(f"(arricchimento web non disponibile: {e})")


def main() -> None:
    p = argparse.ArgumentParser(description="Query DNA")
    p.add_argument("rsid", nargs="?")
    p.add_argument("--gene")
    p.add_argument("--web", action="store_true")
    args = p.parse_args()
    if not args.rsid and not args.gene:
        raise SystemExit("Serve un rsID o --gene")
    res = lookup(rsid=args.rsid, gene=args.gene)
    print(f"Genotipo: {res['genotype'] or 'non nel raw'}")
    for a in res["annotations"]:
        print(f"  [{a['layer']}] " + ", ".join(
            f"{k}={v}" for k, v in a.items() if k not in ("layer",) and v))
    if args.web and args.rsid:
        _web(args.rsid)


if __name__ == "__main__":
    main()
