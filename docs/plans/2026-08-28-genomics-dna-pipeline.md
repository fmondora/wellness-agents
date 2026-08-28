# Genomics DNA Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dare al genetista (plugin `genomics`) una pipeline deterministica che ingerisce raw 23andMe, lo annota contro 4 strati (ClinVar, PharmGKB, GWAS, pannelli curati) e genera report riproducibili.

**Architecture:** 4 script CLI Python (ingest → annotate → report + query) su SQLite in `data/dna/` del repo dati; pannelli curati come JSON nel plugin; server MCP SQLite dichiarato nel manifest. Spec: `docs/specs/2026-08-28-genomics-dna-pipeline-design.md`.

**Tech Stack:** Python 3.12 stdlib (sqlite3, gzip, csv, urllib, json, hashlib) + `openpyxl` SOLO per xlsx (import guardato). Test: pytest.

## Global Constraints

- Repo di lavoro: `/Users/fmondora/wip/personal/wellness-agents` (plugin `genomics/`).
- Data root: `Path(os.environ.get("WELLNESS_DATA", Path.cwd()))` — MAI path assoluti dell'utente nel codice.
- ZERO dati personali nel plugin: fixture solo con genotipi INVENTATI, mai reali.
- Determinismo: stesso input + stessa versione DB ⇒ output byte-identico (niente timestamp negli output salvo la sezione Fonti dei report, che riporta la versione DB — non l'ora).
- Build: il join usa solo DB della build dichiarata in `meta` (il raw 23andMe v5 è GRCh37).
- Report in italiano; header disclaimer clinico ESATTO come da spec (Task 8).
- Commit frequenti, messaggi `feat(genomics): ...` con firma `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Esecuzione test: `cd /Users/fmondora/wip/personal/wellness-agents && python3.12 -m pytest genomics/scripts/tests/ -v`.

---

### Task 1: Modulo comune `dna_common.py`

**Files:**
- Create: `genomics/scripts/dna_common.py`
- Create: `genomics/scripts/tests/__init__.py` (vuoto)
- Test: `genomics/scripts/tests/test_dna_common.py`

**Interfaces:**
- Produces: `data_root() -> Path`, `dna_dir() -> Path`, `db_path() -> Path`, `connect() -> sqlite3.Connection` (crea schema), `get_meta(con, key) -> str|None`, `set_meta(con, key, value)`, `file_sha256(path) -> str`, `load_versions() -> dict`, `save_versions(dict)` (su `data/dna/db/versions.json`).

- [ ] **Step 1: Write the failing test**

```python
# genomics/scripts/tests/test_dna_common.py
import sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_connect_creates_schema_under_wellness_data(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common
    con = dna_common.connect()
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"genotypes", "meta"} <= tables
    assert (tmp_path / "data" / "dna" / "genotypes.db").exists()
    dna_common.set_meta(con, "build", "GRCh37")
    assert dna_common.get_meta(con, "build") == "GRCh37"
    assert dna_common.get_meta(con, "assente") is None
    con.close()


def test_file_sha256_and_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common
    f = tmp_path / "x.txt"
    f.write_text("ciao")
    h = dna_common.file_sha256(f)
    assert len(h) == 64 and h == dna_common.file_sha256(f)
    assert dna_common.load_versions() == {}
    dna_common.save_versions({"clinvar": "2026-08"})
    assert dna_common.load_versions() == {"clinvar": "2026-08"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest genomics/scripts/tests/test_dna_common.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'dna_common'`)

- [ ] **Step 3: Write minimal implementation**

```python
# genomics/scripts/dna_common.py
"""Utilità condivise della pipeline DNA (plugin genomics, wellness-agents)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS genotypes(
  rsid TEXT PRIMARY KEY,
  chrom TEXT,
  pos INTEGER,
  genotype TEXT,
  source_file TEXT,
  build TEXT
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def data_root() -> Path:
    return Path(os.environ.get("WELLNESS_DATA", Path.cwd()))


def dna_dir() -> Path:
    return data_root() / "data" / "dna"


def db_path() -> Path:
    return dna_dir() / "genotypes.db"


def connect() -> sqlite3.Connection:
    dna_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path())
    con.executescript(SCHEMA)
    return con


def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.commit()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _versions_path() -> Path:
    return dna_dir() / "db" / "versions.json"


def load_versions() -> dict:
    p = _versions_path()
    return json.loads(p.read_text()) if p.exists() else {}


def save_versions(v: dict) -> None:
    p = _versions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=1, ensure_ascii=False, sort_keys=True))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3.12 -m pytest genomics/scripts/tests/test_dna_common.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add genomics/scripts/dna_common.py genomics/scripts/tests/
git commit -m "feat(genomics): modulo comune pipeline DNA (paths, sqlite, versioni)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `dna_ingest.py` — formato txt 23andMe + idempotenza

**Files:**
- Create: `genomics/scripts/dna_ingest.py`
- Create: `genomics/scripts/tests/fixtures/sample_23andme.txt`
- Test: `genomics/scripts/tests/test_dna_ingest.py`

**Interfaces:**
- Consumes: `dna_common.connect/set_meta/get_meta/file_sha256`
- Produces: CLI `dna_ingest.py <file> [--build GRCh37]`; funzione `ingest(path: Path, build: str = "GRCh37") -> dict` che ritorna `{"inserted": int, "skipped_nocall": int, "status": "ok"|"already_ingested"}`. Righe no-call (`--`) NON entrano in `genotypes`.

- [ ] **Step 1: Create the fixture (genotipi INVENTATI)**

```
# genomics/scripts/tests/fixtures/sample_23andme.txt
# Questo file è una FIXTURE SINTETICA: genotipi inventati, nessuna persona reale.
# rsid	chromosome	position	genotype
rs1000001	1	1000	AA
rs1000002	1	2000	AG
rs1000003	2	3000	CT
rs1000004	5	132000	CC
rs1000005	5	132100	TT
rs1000006	10	45000	AC
rs1000007	17	38000	GG
rs1000008	22	21000	CT
rs1000009	3	9000	--
rs1000010	4	7000	DI
```

- [ ] **Step 2: Write the failing test**

```python
# genomics/scripts/tests/test_dna_ingest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_txt(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest
    res = dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    assert res["status"] == "ok"
    assert res["inserted"] == 9          # tutte tranne il no-call
    assert res["skipped_nocall"] == 1
    con = dna_common.connect()
    row = con.execute(
        "SELECT genotype, chrom, pos, build FROM genotypes WHERE rsid='rs1000002'"
    ).fetchone()
    assert row == ("AG", "1", 2000, "GRCh37")
    # l'indel resta (DI è un genotipo valido del chip), il no-call no
    assert con.execute("SELECT COUNT(*) FROM genotypes").fetchone()[0] == 9
    assert dna_common.get_meta(con, "build") == "GRCh37"


def test_ingest_idempotente(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest
    first = dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    second = dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    assert first["status"] == "ok"
    assert second["status"] == "already_ingested"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3.12 -m pytest genomics/scripts/tests/test_dna_ingest.py -v`
Expected: FAIL (`No module named 'dna_ingest'`)

- [ ] **Step 4: Write minimal implementation**

```python
# genomics/scripts/dna_ingest.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3.12 -m pytest genomics/scripts/tests/test_dna_ingest.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add genomics/scripts/dna_ingest.py genomics/scripts/tests/
git commit -m "feat(genomics): dna_ingest per txt 23andMe, idempotente, no-call esclusi

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `dna_ingest.py` — formati xlsx e VCF minimale

**Files:**
- Modify: `genomics/scripts/dna_ingest.py`
- Create: `genomics/scripts/tests/fixtures/make_xlsx_fixture.py`
- Create: `genomics/scripts/tests/fixtures/sample.vcf`
- Test: `genomics/scripts/tests/test_dna_ingest.py` (aggiunta)

**Interfaces:**
- Produces: `ingest()` invariato ma con autodetect: `.txt` → txt, `.vcf` → vcf, `.xlsx` → xlsx (openpyxl guardato: se assente, `SystemExit` con messaggio `pip install openpyxl`). Per xlsx: la riga d'intestazione dati è quella che contiene le colonne (case-insensitive) `rsid`, `chromosome`, `position`, `genotype` — cercata nelle prime 50 righe.

- [ ] **Step 1: Create VCF fixture e generatore xlsx**

```
# genomics/scripts/tests/fixtures/sample.vcf
##fileformat=VCFv4.2
##FIXTURE SINTETICA — genotipi inventati
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
1	1000	rs1000001	A	G	.	.	.	GT	0/0
1	2000	rs1000002	A	G	.	.	.	GT	0/1
2	3000	rs1000003	C	T	.	.	.	GT	0/1
```

```python
# genomics/scripts/tests/fixtures/make_xlsx_fixture.py
"""Genera sample.xlsx (fixture sintetica). Eseguire una volta: richiede openpyxl."""
from pathlib import Path
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["Report genotipi — FIXTURE SINTETICA"])
ws.append([])
ws.append(["rsid", "chromosome", "position", "genotype"])
for row in [("rs1000001", "1", 1000, "AA"), ("rs1000002", "1", 2000, "AG"),
            ("rs1000009", "3", 9000, "--")]:
    ws.append(row)
wb.save(Path(__file__).parent / "sample.xlsx")
print("scritto sample.xlsx")
```

Run: `python3.12 genomics/scripts/tests/fixtures/make_xlsx_fixture.py` (se openpyxl manca: `python3.12 -m pip install --user openpyxl`). Committare lo xlsx generato.

- [ ] **Step 2: Write the failing tests (append al file esistente)**

```python
# append a genomics/scripts/tests/test_dna_ingest.py
def test_ingest_vcf(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest
    res = dna_ingest.ingest(FIXTURES / "sample.vcf")
    assert res["inserted"] == 3
    con = dna_common.connect()
    # 0/0 su REF=A → AA; 0/1 → AG (REF+ALT, ordine alfabetico non richiesto)
    assert con.execute(
        "SELECT genotype FROM genotypes WHERE rsid='rs1000001'").fetchone()[0] == "AA"
    assert con.execute(
        "SELECT genotype FROM genotypes WHERE rsid='rs1000002'").fetchone()[0] == "AG"


def test_ingest_xlsx(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import pytest
    pytest.importorskip("openpyxl")
    import dna_ingest
    res = dna_ingest.ingest(FIXTURES / "sample.xlsx")
    assert res["inserted"] == 2 and res["skipped_nocall"] == 1
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python3.12 -m pytest genomics/scripts/tests/test_dna_ingest.py -v`
Expected: i 2 nuovi test FAIL, i vecchi PASS

- [ ] **Step 4: Implement — sostituire `_rows_txt`-only con dispatch**

```python
# in genomics/scripts/dna_ingest.py — aggiungere dopo _rows_txt:

def _rows_vcf(path: Path):
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 10 or not f[2].startswith("rs"):
            continue
        chrom, pos, rsid, ref, alt = f[0], int(f[1]), f[2], f[3], f[4]
        gt_field = f[9].split(":")[0].replace("|", "/")
        alleles = {"0": ref, "1": alt.split(",")[0]}
        try:
            a, b = gt_field.split("/")
            gt = alleles[a] + alleles[b]
        except (ValueError, KeyError):
            gt = "--"
        yield rsid, chrom, pos, gt


def _rows_xlsx(path: Path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise SystemExit("Per i file xlsx serve openpyxl: python3.12 -m pip install openpyxl")
    ws = load_workbook(path, read_only=True).active
    want = ["rsid", "chromosome", "position", "genotype"]
    idx = None
    for row in ws.iter_rows(max_row=50, values_only=True):
        low = [str(c).strip().lower() if c else "" for c in row]
        if all(w in low for w in want):
            idx = {w: low.index(w) for w in want}
            header_found = row
            break
    if idx is None:
        raise SystemExit(f"{path.name}: intestazione dati non trovata (colonne attese: {want})")
    started = False
    for row in ws.iter_rows(values_only=True):
        if not started:
            started = row == header_found
            continue
        if row[idx["rsid"]] is None:
            continue
        yield (str(row[idx["rsid"]]), str(row[idx["chromosome"]]),
               int(row[idx["position"]]), str(row[idx["genotype"]]).strip())


READERS = {".txt": _rows_txt, ".vcf": _rows_vcf, ".xlsx": _rows_xlsx}

# in ingest(): sostituire `for ... in _rows_txt(path)` con:
#   reader = READERS.get(path.suffix.lower())
#   if reader is None:
#       raise SystemExit(f"Formato non supportato: {path.suffix} (attesi: {sorted(READERS)})")
#   for rsid, chrom, pos, gt in reader(path):
```

- [ ] **Step 5: Run tests to verify PASS**

Run: `python3.12 -m pytest genomics/scripts/tests/test_dna_ingest.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add genomics/scripts/
git commit -m "feat(genomics): ingest xlsx (openpyxl guardato) e VCF minimale con autodetect

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Pannelli curati + strato `panels` di `dna_annotate.py`

**Files:**
- Create: `genomics/knowledge/panels/th2.json`
- Create: `genomics/knowledge/panels/metilazione.json`
- Create: `genomics/scripts/dna_annotate.py`
- Test: `genomics/scripts/tests/test_annotate_panels.py`
- Create: `genomics/scripts/tests/fixtures/panels/test_panel.json`

**Interfaces:**
- Consumes: `dna_common`, `genotypes.db` popolato.
- Produces: CLI `dna_annotate.py --layer panels [--panels-dir DIR]`; funzione `annotate_panels(panels_dir: Path) -> int` (numero righe annotate). Output: `data/dna/annotated/panels.jsonl` (una riga JSON per SNP trovato: `{"rsid","genotype","panel","gene","label","effect","relevance","source":"panel:<file>","db_version":"plugin"}`) + tabella `annotations_panels(rsid, panel, gene, label, effect, relevance)` ricreata a ogni run (DROP+CREATE: idempotenza). Default `--panels-dir` = `Path(__file__).parent.parent / "knowledge" / "panels"`.
- Schema pannello: `{"panel": str, "pathway": str, "snps": [{"rsid","gene","label","interpretations": {"<GT>": {"effect","relevance"}}, "refs": [...]}]}`. Genotipo cercato anche invertito (es. `AG`→`GA`); `relevance` ∈ `{"alta","media","bassa","neutro"}`.

- [ ] **Step 1: Fixture pannello di test (rsID della fixture raw)**

```json
// genomics/scripts/tests/fixtures/panels/test_panel.json
{
  "panel": "test",
  "pathway": "Pathway di Test",
  "snps": [
    {"rsid": "rs1000002", "gene": "GENEX", "label": "GENEX promoter",
     "interpretations": {
       "AA": {"effect": "wild type", "relevance": "neutro"},
       "AG": {"effect": "eterozigote, attività ridotta", "relevance": "media"},
       "GG": {"effect": "omozigote, attività molto ridotta", "relevance": "alta"}}},
    {"rsid": "rs9999999", "gene": "ASSENTE", "label": "non nel raw",
     "interpretations": {"CC": {"effect": "x", "relevance": "bassa"}}}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# genomics/scripts/tests/test_annotate_panels.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_annotate_panels(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    n = dna_annotate.annotate_panels(FIXTURES / "panels")
    assert n == 1  # rs1000002 c'è (AG), rs9999999 no
    out = tmp_path / "data" / "dna" / "annotated" / "panels.jsonl"
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows[0]["rsid"] == "rs1000002"
    assert rows[0]["effect"] == "eterozigote, attività ridotta"
    assert rows[0]["relevance"] == "media"
    con = dna_common.connect()
    assert con.execute("SELECT COUNT(*) FROM annotations_panels").fetchone()[0] == 1
    # idempotenza: seconda run identica, non duplicata
    assert dna_annotate.annotate_panels(FIXTURES / "panels") == 1
    assert con.execute("SELECT COUNT(*) FROM annotations_panels").fetchone()[0] == 1


def test_genotipo_invertito(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    con = dna_common.connect()
    con.execute("UPDATE genotypes SET genotype='GA' WHERE rsid='rs1000002'")
    con.commit()
    assert dna_annotate.annotate_panels(FIXTURES / "panels") == 1
```

- [ ] **Step 3: Run to verify FAIL** — `python3.12 -m pytest genomics/scripts/tests/test_annotate_panels.py -v` → `No module named 'dna_annotate'`

- [ ] **Step 4: Implement**

```python
# genomics/scripts/dna_annotate.py
"""Annotazione deterministica dei genotipi per strato. Output: jsonl + tabelle sqlite."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dna_common

DEFAULT_PANELS = Path(__file__).resolve().parent.parent / "knowledge" / "panels"


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
```

- [ ] **Step 5: Run tests** → 2 PASS (`test_annotate_panels.py`); l'intera suite resta verde.

- [ ] **Step 6: Scrivere i due pannelli seed reali (letteratura pubblica, NESSUN genotipo personale)**

```json
// genomics/knowledge/panels/th2.json
{
  "panel": "th2",
  "pathway": "Th2 / Infiammazione allergica",
  "snps": [
    {"rsid": "rs2243250", "gene": "IL4", "label": "IL-4 promoter -589C>T",
     "interpretations": {
       "CC": {"effect": "wild type — produzione IL-4 tipica", "relevance": "neutro"},
       "CT": {"effect": "eterozigote — aumentata espressione IL-4, predisposizione Th2", "relevance": "alta"},
       "TT": {"effect": "omozigote — espressione IL-4 elevata, forte predisposizione Th2", "relevance": "alta"}}},
    {"rsid": "rs20541", "gene": "IL13", "label": "IL-13 R130Q",
     "interpretations": {
       "GG": {"effect": "wild type", "relevance": "neutro"},
       "AG": {"effect": "eterozigote — IL-13 più attiva, associata ad asma/atopia", "relevance": "alta"},
       "AA": {"effect": "omozigote — variante R130Q su entrambi gli alleli", "relevance": "alta"}}},
    {"rsid": "rs1800925", "gene": "IL13", "label": "IL-13 promoter -1112C>T",
     "interpretations": {
       "CC": {"effect": "wild type", "relevance": "neutro"},
       "CT": {"effect": "eterozigote — promoter più attivo", "relevance": "media"},
       "TT": {"effect": "omozigote — espressione IL-13 aumentata", "relevance": "alta"}}},
    {"rsid": "rs7216389", "gene": "GSDMB/ORMDL3", "label": "locus 17q21 asma infantile",
     "interpretations": {
       "CC": {"effect": "wild type", "relevance": "neutro"},
       "CT": {"effect": "eterozigote — rischio 17q21 intermedio", "relevance": "media"},
       "TT": {"effect": "omozigote — rischio 17q21", "relevance": "alta"}}}
  ],
  "refs": ["PMID:9226976", "PMID:17611496"]
}
```

```json
// genomics/knowledge/panels/metilazione.json
{
  "panel": "metilazione",
  "pathway": "Metilazione / Omocisteina / Vitamine B",
  "snps": [
    {"rsid": "rs1801133", "gene": "MTHFR", "label": "MTHFR C677T",
     "interpretations": {
       "GG": {"effect": "wild type — attività MTHFR piena", "relevance": "neutro"},
       "AG": {"effect": "eterozigote — attività ~65%", "relevance": "media"},
       "AA": {"effect": "omozigote — attività ~30%, folati attivi consigliabili (parlarne col medico)", "relevance": "alta"}}},
    {"rsid": "rs1801131", "gene": "MTHFR", "label": "MTHFR A1298C",
     "interpretations": {
       "TT": {"effect": "wild type", "relevance": "neutro"},
       "GT": {"effect": "eterozigote — lieve riduzione", "relevance": "bassa"},
       "GG": {"effect": "omozigote — riduzione moderata", "relevance": "media"}}},
    {"rsid": "rs1805087", "gene": "MTR", "label": "MTR A2756G (metionina sintasi)",
     "interpretations": {
       "AA": {"effect": "wild type", "relevance": "neutro"},
       "AG": {"effect": "eterozigote — possibile maggiore fabbisogno B12", "relevance": "media"},
       "GG": {"effect": "omozigote — rimetilazione B12-dipendente ridotta", "relevance": "alta"}}},
    {"rsid": "rs1801394", "gene": "MTRR", "label": "MTRR A66G",
     "interpretations": {
       "AA": {"effect": "wild type", "relevance": "neutro"},
       "AG": {"effect": "eterozigote — rigenerazione MTR ridotta", "relevance": "media"},
       "GG": {"effect": "omozigote — rigenerazione MTR compromessa", "relevance": "media"}}},
    {"rsid": "rs4680", "gene": "COMT", "label": "COMT Val158Met",
     "interpretations": {
       "GG": {"effect": "Val/Val — COMT veloce, catecolamine smaltite rapidamente", "relevance": "bassa"},
       "AG": {"effect": "Val/Met — metabolismo catecolamine intermedio", "relevance": "bassa"},
       "AA": {"effect": "Met/Met — COMT lenta, catecolamine più persistenti", "relevance": "media"}}}
  ],
  "refs": ["PMID:7647779", "PMID:10195245"]
}
```

- [ ] **Step 7: Commit**

```bash
git add genomics/scripts/ genomics/knowledge/panels/
git commit -m "feat(genomics): strato panels con pannelli curati th2 e metilazione

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Strato `clinvar` (download cache + join)

**Files:**
- Modify: `genomics/scripts/dna_annotate.py`
- Create: `genomics/scripts/tests/fixtures/mini_clinvar_GRCh37.vcf.gz` (generata nel test setup, vedi Step 1)
- Test: `genomics/scripts/tests/test_annotate_clinvar.py`

**Interfaces:**
- Produces: `annotate_clinvar(update: bool = False, vcf_path: Path | None = None) -> int`. Con `vcf_path` esplicito NIENTE download (via per i test). Senza: usa `data/dna/db/clinvar_GRCh37.vcf.gz`; se assente o `update=True`, scarica da `https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh37/clinvar.vcf.gz` e registra in versions.json la data `clinvar` presa dall'header `##fileDate=`. Se il build in `meta` non è GRCh37 → `SystemExit` (mai mescolare build). Join: righe VCF con `RS=` o ID `rs*` presenti in `genotypes`; estrae `CLNSIG`, `CLNDN`, `GENEINFO` dall'INFO. Output: `annotated/clinvar.jsonl` + `annotations_clinvar(rsid, genotype, clnsig, condition, gene)`.

- [ ] **Step 1: Write the failing test (con mini-VCF costruito dal test)**

```python
# genomics/scripts/tests/test_annotate_clinvar.py
import gzip, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

MINI = """##fileformat=VCFv4.1
##fileDate=2026-08-01
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
1\t2000\trs1000002\tA\tG\t.\t.\tRS=1000002;CLNSIG=Pathogenic;CLNDN=Malattia_Finta;GENEINFO=GENEX:111
2\t3000\trs1000003\tC\tT\t.\t.\tRS=1000003;CLNSIG=Benign;CLNDN=not_provided;GENEINFO=GENEY:222
9\t9999\trs7777777\tG\tA\t.\t.\tRS=7777777;CLNSIG=Pathogenic;CLNDN=Altra;GENEINFO=GENEZ:333
"""


def _mini_vcf(tmp_path) -> Path:
    p = tmp_path / "mini_clinvar.vcf.gz"
    with gzip.open(p, "wt") as fh:
        fh.write(MINI)
    return p


def test_annotate_clinvar_join(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    n = dna_annotate.annotate_clinvar(vcf_path=_mini_vcf(tmp_path))
    assert n == 2  # rs7777777 non è nel raw
    rows = [json.loads(l) for l in
            (tmp_path / "data/dna/annotated/clinvar.jsonl").read_text().splitlines()]
    patho = next(r for r in rows if r["rsid"] == "rs1000002")
    assert patho["clnsig"] == "Pathogenic" and patho["genotype"] == "AG"
    assert patho["gene"] == "GENEX"


def test_build_mismatch_blocca(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import pytest, dna_common, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt", build="GRCh38")
    with pytest.raises(SystemExit):
        dna_annotate.annotate_clinvar(vcf_path=_mini_vcf(tmp_path))
```

- [ ] **Step 2: Run to verify FAIL** → `AttributeError: ... no attribute 'annotate_clinvar'`

- [ ] **Step 3: Implement (aggiungere a dna_annotate.py)**

```python
# aggiungere in genomics/scripts/dna_annotate.py
import gzip
import urllib.request

CLINVAR_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh37/clinvar.vcf.gz"


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
```

- [ ] **Step 4: Run tests** → 2 PASS; suite intera verde.

- [ ] **Step 5: Commit**

```bash
git add genomics/scripts/
git commit -m "feat(genomics): strato clinvar con cache versionata e guardia sul build

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Strato `gwas` (GWAS Catalog TSV)

**Files:**
- Modify: `genomics/scripts/dna_annotate.py`
- Test: `genomics/scripts/tests/test_annotate_gwas.py`

**Interfaces:**
- Produces: `annotate_gwas(update: bool = False, tsv_path: Path | None = None) -> int`. Cache: `data/dna/db/gwas_catalog.tsv` da `https://www.ebi.ac.uk/gwas/api/search/downloads/alternative`; versione = data di download registrata SOLO al download (deterministico tra run sulla stessa cache). Join su colonna `SNPS` (può contenere più rsID separati da `; ` o ` x `): match se UNO è nel raw. Estrae `DISEASE/TRAIT`, `P-VALUE`, `OR or BETA`, `MAPPED_GENE`, `STUDY ACCESSION`. Output: `annotated/gwas.jsonl` + `annotations_gwas(rsid, genotype, trait, p_value, effect, gene, study)`.

- [ ] **Step 1: Write the failing test**

```python
# genomics/scripts/tests/test_annotate_gwas.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

HEADER = "DATE ADDED TO CATALOG\tPUBMEDID\tFIRST AUTHOR\tDATE\tJOURNAL\tLINK\tSTUDY\tDISEASE/TRAIT\tINITIAL SAMPLE SIZE\tREPLICATION SAMPLE SIZE\tREGION\tCHR_ID\tCHR_POS\tREPORTED GENE(S)\tMAPPED_GENE\tUPSTREAM_GENE_ID\tDOWNSTREAM_GENE_ID\tSNP_GENE_IDS\tUPSTREAM_GENE_DISTANCE\tDOWNSTREAM_GENE_DISTANCE\tSTRONGEST SNP-RISK ALLELE\tSNPS\tMERGED\tSNP_ID_CURRENT\tCONTEXT\tINTERGENIC\tRISK ALLELE FREQUENCY\tP-VALUE\tPVALUE_MLOG\tP-VALUE (TEXT)\tOR or BETA\t95% CI (TEXT)\tPLATFORM [SNPS PASSING QC]\tCNV\tMAPPED_TRAIT\tMAPPED_TRAIT_URI\tSTUDY ACCESSION\tGENOTYPING TECHNOLOGY"


def _mini_tsv(tmp_path) -> Path:
    def row(snps, trait, p, orb, gene, acc):
        cells = [""] * 38
        cells[7], cells[14], cells[21], cells[27], cells[30], cells[35] = trait, gene, snps, p, orb, acc
        return "\t".join(cells)
    p = tmp_path / "mini_gwas.tsv"
    p.write_text("\n".join([HEADER,
        row("rs1000003", "Tratto Finto A", "3E-12", "1.21", "GENEY", "GCST900001"),
        row("rs1000007; rs5555555", "Tratto Finto B", "2E-9", "0.88", "GENEW", "GCST900002"),
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
```

- [ ] **Step 2: FAIL** → `no attribute 'annotate_gwas'`

- [ ] **Step 3: Implement (aggiungere a dna_annotate.py)**

```python
# aggiungere in genomics/scripts/dna_annotate.py
import csv
from datetime import date

GWAS_URL = "https://www.ebi.ac.uk/gwas/api/search/downloads/alternative"


def _gwas_cache(update: bool) -> Path:
    dest = dna_common.dna_dir() / "db" / "gwas_catalog.tsv"
    if dest.exists() and not update:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Scarico GWAS Catalog (~700MB) da {GWAS_URL} ...")
    try:
        urllib.request.urlretrieve(GWAS_URL, dest)
    except Exception as e:
        if dest.exists():
            print(f"Download fallito ({e}): uso la cache esistente.")
            return dest
        raise SystemExit(f"Download GWAS Catalog fallito e nessuna cache: {e}")
    versions = dna_common.load_versions()
    versions["gwas"] = date.today().isoformat()
    dna_common.save_versions(versions)
    return dest


def annotate_gwas(update: bool = False, tsv_path: Path | None = None) -> int:
    gts = _genotypes()
    path = tsv_path or _gwas_cache(update)
    version = dna_common.load_versions().get("gwas", "cache-locale")
    rows = []
    with open(path, newline="") as fh:
        for rec in csv.DictReader(fh, delimiter="\t"):
            snps = rec.get("SNPS", "")
            for token in snps.replace(" x ", ";").split(";"):
                rsid = token.strip()
                if rsid in gts:
                    rows.append({"rsid": rsid, "genotype": gts[rsid],
                                 "trait": rec.get("DISEASE/TRAIT", ""),
                                 "p_value": rec.get("P-VALUE", ""),
                                 "effect": rec.get("OR or BETA", ""),
                                 "gene": rec.get("MAPPED_GENE", ""),
                                 "study": rec.get("STUDY ACCESSION", ""),
                                 "source": "gwas", "db_version": version})
                    break
    return _write_layer("gwas", rows,
                        ["rsid", "genotype", "trait", "p_value", "effect", "gene", "study"])
```

- [ ] **Step 4: PASS + suite verde** — [ ] **Step 5: Commit** (`feat(genomics): strato gwas da GWAS Catalog TSV` + firma)

---

### Task 7: Strato `pharmgkb` (dump locale, niente download automatico)

**Files:**
- Modify: `genomics/scripts/dna_annotate.py`
- Test: `genomics/scripts/tests/test_annotate_pharmgkb.py`

**Interfaces:**
- Produces: `annotate_pharmgkb(dump_dir: Path | None = None) -> int`. Legge `data/dna/db/pharmgkb/clinical_annotations.tsv` (dall'archivio "clinicalAnnotations.zip" che l'utente scarica da pharmgkb.org con account gratuito — istruzioni nell'errore se manca). Colonne usate: `Variant/Haplotypes`, `Gene`, `Level of Evidence`, `Drug(s)`, `Phenotype Category`, `Clinical Annotation ID`. Tiene solo varianti `rs*` presenti nel raw. Versione: dal file `CREATED_*.txt` nel dump se presente, altrimenti `"dump-locale"`. Output: `annotated/pharmgkb.jsonl` + `annotations_pharmgkb(rsid, genotype, gene, level, drugs, category, ann_id)`.

- [ ] **Step 1: Write the failing test**

```python
# genomics/scripts/tests/test_annotate_pharmgkb.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

TSV = ("Clinical Annotation ID\tVariant/Haplotypes\tGene\tLevel of Evidence\t"
       "Level Override\tLevel Modifiers\tScore\tPhenotype Category\tPMID Count\t"
       "Evidence Count\tDrug(s)\tPhenotype(s)\tLatest History Date (YYYY-MM-DD)\t"
       "URL\tSpecialty Population\n"
       "981\trs1000006\tCYPX\t1A\t\t\t100\tMetabolism/PK\t5\t7\tfarmacone\tnessuno\t2026-01-01\thttp://x\t\n"
       "982\tCYP2D6*4\tCYP2D6\t1A\t\t\t90\tMetabolism/PK\t3\t4\taltro\tnessuno\t2026-01-01\thttp://x\t\n"
       "983\trs4242424\tGENEQ\t2B\t\t\t20\tEfficacy\t1\t1\tterzo\tnessuno\t2026-01-01\thttp://x\t\n")


def test_annotate_pharmgkb(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dump = tmp_path / "data" / "dna" / "db" / "pharmgkb"
    dump.mkdir(parents=True)
    (dump / "clinical_annotations.tsv").write_text(TSV)
    n = dna_annotate.annotate_pharmgkb()
    assert n == 1  # solo rs1000006: l'aplotipo *4 e l'rs assente sono esclusi
    row = json.loads((tmp_path / "data/dna/annotated/pharmgkb.jsonl").read_text())
    assert row["level"] == "1A" and row["drugs"] == "farmacone" and row["genotype"] == "AC"


def test_pharmgkb_dump_mancante(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import pytest, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    with pytest.raises(SystemExit, match="pharmgkb.org"):
        dna_annotate.annotate_pharmgkb()
```

- [ ] **Step 2: FAIL** → [ ] **Step 3: Implement**

```python
# aggiungere in genomics/scripts/dna_annotate.py
def annotate_pharmgkb(dump_dir: Path | None = None) -> int:
    dump = dump_dir or (dna_common.dna_dir() / "db" / "pharmgkb")
    tsv = dump / "clinical_annotations.tsv"
    if not tsv.exists():
        raise SystemExit(
            "Dump PharmGKB non trovato.\n"
            f"Scarica 'clinicalAnnotations.zip' da https://www.pharmgkb.org/downloads\n"
            f"(account gratuito) ed estrai clinical_annotations.tsv in {dump}/")
    created = sorted(dump.glob("CREATED_*.txt"))
    version = created[-1].stem.replace("CREATED_", "") if created else "dump-locale"
    gts = _genotypes()
    rows = []
    with open(tsv, newline="") as fh:
        for rec in csv.DictReader(fh, delimiter="\t"):
            variant = rec.get("Variant/Haplotypes", "").strip()
            if not variant.startswith("rs") or variant not in gts:
                continue
            rows.append({"rsid": variant, "genotype": gts[variant],
                         "gene": rec.get("Gene", ""),
                         "level": rec.get("Level of Evidence", ""),
                         "drugs": rec.get("Drug(s)", ""),
                         "category": rec.get("Phenotype Category", ""),
                         "ann_id": rec.get("Clinical Annotation ID", ""),
                         "source": "pharmgkb", "db_version": version})
    versions = dna_common.load_versions()
    versions["pharmgkb"] = version
    dna_common.save_versions(versions)
    return _write_layer("pharmgkb", rows,
                        ["rsid", "genotype", "gene", "level", "drugs", "category", "ann_id"])
```

- [ ] **Step 4: PASS + suite verde** — [ ] **Step 5: Commit** (`feat(genomics): strato pharmgkb da dump locale con istruzioni se assente` + firma)

---

### Task 8: `dna_report.py` — kb/genomica.md + report per strato

**Files:**
- Create: `genomics/scripts/dna_report.py`
- Test: `genomics/scripts/tests/test_dna_report.py`

**Interfaces:**
- Consumes: tabelle `annotations_*` in sqlite + `versions.json` + `meta`.
- Produces: CLI `dna_report.py [--layer panels|clinvar|pharmgkb|gwas]` (default: tutti gli strati con tabella presente). Funzioni: `report_panels() -> Path` (scrive `kb/genomica.md` nel repo dati), `report_clinvar() -> Path`, `report_pharmgkb() -> Path`, `report_gwas() -> Path` (scrivono in `data/dna/reports/`). Determinismo: contenuto funzione SOLO di db+versioni (nessun timestamp).
- Header clinico ESATTO (costante `DISCLAIMER_CLINICO`): `> ⚠️ **Dati da chip array: falsi positivi noti.** Ogni variante patogenica va confermata con sequenziamento clinico e valutata con un genetista medico. Questo report non è una diagnosi.`

- [ ] **Step 1: Write the failing test**

```python
# genomics/scripts/tests/test_dna_report.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import gzip, dna_ingest, dna_annotate
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    from test_annotate_clinvar import MINI
    vcf = tmp_path / "mini.vcf.gz"
    with gzip.open(vcf, "wt") as fh:
        fh.write(MINI)
    dna_annotate.annotate_clinvar(vcf_path=vcf)


def test_report_panels_scrive_kb(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import dna_report
    out = dna_report.report_panels()
    text = out.read_text()
    assert out == tmp_path / "kb" / "genomica.md"
    assert "## Pathway di Test" in text
    assert "| GENEX | rs1000002 | AG | eterozigote, attività ridotta |" in text
    assert "## Fonti" in text and "GRCh37" in text


def test_report_clinvar_ha_disclaimer_e_solo_patogeniche(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import dna_report
    text = dna_report.report_clinvar().read_text()
    assert text.startswith("# Report ClinVar")
    assert dna_report.DISCLAIMER_CLINICO in text
    assert "rs1000002" in text        # Pathogenic
    assert "rs1000003" not in text    # Benign: fuori dal report


def test_determinismo(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import dna_report
    a = dna_report.report_panels().read_text()
    b = dna_report.report_panels().read_text()
    assert a == b
```

- [ ] **Step 2: FAIL** → [ ] **Step 3: Implement**

```python
# genomics/scripts/dna_report.py
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
```

- [ ] **Step 4: PASS (3 test) + suite verde** — [ ] **Step 5: Commit** (`feat(genomics): dna_report — kb rigenerabile + report per strato con disclaimer` + firma)

---

### Task 9: `dna_query.py`

**Files:**
- Create: `genomics/scripts/dna_query.py`
- Test: `genomics/scripts/tests/test_dna_query.py`

**Interfaces:**
- Produces: CLI `dna_query.py <rsid> | --gene NOME [--web]`; funzione `lookup(rsid: str | None = None, gene: str | None = None) -> dict` con chiavi `genotype` (str|None) e `annotations` (lista di dict con campo `layer`). `--web` (solo CLI): stampa in più l'URL pubblico `https://www.ncbi.nlm.nih.gov/snp/<rsid>` e, se la rete risponde, il riassunto da `https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/<numero>` — inviando SOLO l'rsID; fallimento rete = messaggio, mai errore.

- [ ] **Step 1: Write the failing test**

```python
# genomics/scripts/tests/test_dna_query.py
import gzip, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def test_lookup_rsid_e_gene(tmp_path, monkeypatch):
    monkeypatch.setenv("WELLNESS_DATA", str(tmp_path))
    import dna_ingest, dna_annotate, dna_query
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    res = dna_query.lookup(rsid="rs1000002")
    assert res["genotype"] == "AG"
    assert res["annotations"][0]["layer"] == "panels"
    assert res["annotations"][0]["gene"] == "GENEX"
    by_gene = dna_query.lookup(gene="GENEX")
    assert any(a["rsid"] == "rs1000002" for a in by_gene["annotations"])
    assert dna_query.lookup(rsid="rs404")["genotype"] is None
```

- [ ] **Step 2: FAIL** → [ ] **Step 3: Implement**

```python
# genomics/scripts/dna_query.py
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
    return [r[0].replace("annotations_", "") for r in con.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'annotations_%'")]


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
```

- [ ] **Step 4: PASS + suite verde** — [ ] **Step 5: Commit** (`feat(genomics): dna_query con lookup locale e arricchimento web opzionale (solo rsID)` + firma)

---

### Task 10: Test end-to-end di determinismo

**Files:**
- Test: `genomics/scripts/tests/test_determinism.py`

**Interfaces:** consuma tutto; nessuna produzione nuova.

- [ ] **Step 1: Write the test**

```python
# genomics/scripts/tests/test_determinism.py
import gzip, hashlib, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"


def _run_all(root, monkeypatch) -> str:
    monkeypatch.setenv("WELLNESS_DATA", str(root))
    for m in list(sys.modules):
        if m.startswith("dna_"):
            del sys.modules[m]
    import dna_ingest, dna_annotate, dna_report
    from test_annotate_clinvar import MINI
    vcf = root / "mini.vcf.gz"
    with gzip.open(vcf, "wt") as fh:
        fh.write(MINI)
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    dna_annotate.annotate_clinvar(vcf_path=vcf)
    h = hashlib.sha256()
    for f in sorted((root / "data" / "dna" / "annotated").glob("*.jsonl")):
        h.update(f.read_bytes())
    h.update(dna_report.report_panels().read_bytes())
    h.update(dna_report.report_clinvar().read_bytes())
    return h.hexdigest()


def test_pipeline_deterministica(tmp_path, monkeypatch):
    a = _run_all(tmp_path / "a", monkeypatch)
    b = _run_all(tmp_path / "b", monkeypatch)
    assert a == b
```

- [ ] **Step 2: Run** → PASS (se FAIL: c'è non-determinismo da eliminare — timestamp, ordering, dict non ordinati)
- [ ] **Step 3: Commit** (`test(genomics): determinismo end-to-end della pipeline` + firma)

---

### Task 11: Pannelli rimanenti dal kb esistente

**Files:**
- Create: `genomics/knowledge/panels/nutrizione.json`, `detox-fase1.json`, `detox-fase2.json`, `omega.json`, `vitamina-d.json`, `farmacogenomica-core.json`, `ossidativo.json`, `barriera.json`, `cardiovascolare.json`

**Interfaces:** stesso schema JSON del Task 4.

- [ ] **Step 1: Leggere le sezioni pathway di `/Users/fmondora/wip/personal/lucia/kb/genomica.md`** (repo dati di Francesco — SOLO come indice degli rsID rilevanti per pathway; è l'unica lettura ammessa dal repo dati).
- [ ] **Step 2: Per ogni pathway, creare il pannello** con gli rsID di quella sezione, ma con `interpretations` per TUTTI i genotipi possibili (CC/CT/TT ecc.) sintetizzate dalla letteratura pubblica dell'effetto per allele — MAI copiare la colonna "Genotipo" (è il dato personale) e MAI menzionare condizioni della persona. Ogni effetto è scritto per un utente generico. Rilevanza dal potenziale dell'allele, non dal caso specifico.
- [ ] **Step 3: Validare**: `python3.12 - <<'EOF'` con json.load su tutti i file di `genomics/knowledge/panels/` + verifica chiavi obbligatorie (`panel`, `pathway`, `snps[].rsid/gene/label/interpretations`). Expected: nessun errore.
- [ ] **Step 4: Sweep**: `grep -riE "francesco|CT \||\| AG \|" genomics/knowledge/panels/` non deve restituire genotipi personali copiati (controllo a campione manuale: nessun campo con UN solo genotipo "osservato").
- [ ] **Step 5: Commit** (`feat(genomics): pannelli curati per gli 11 pathway` + firma)

---

### Task 12: Skill `/dna`, AGENT.md, MCP e manifest

**Files:**
- Create: `genomics/skills/dna/SKILL.md`
- Modify: `genomics/AGENT.md` (sezione strumenti — sostituire la sezione Setup esistente resta, si aggiunge "## Strumenti (pipeline)")
- Modify: `genomics/.claude-plugin/plugin.json` (version 0.2.0 + mcpServers)
- Modify: `.claude-plugin/marketplace.json` (description genomics + metadata version 0.8.0)

**Interfaces:** consuma i CLI dei task precedenti.

- [ ] **Step 1: Skill /dna**

```markdown
---
name: dna
description: Query genomica del genetista — interroga il DNA dell'utente (genotipi + annotazioni ClinVar/PharmGKB/GWAS/pannelli), rigenera kb e report. Usa per "gene", "DNA", "SNP", "variante", "come metabolizzo", "rigenera il profilo genomico".
---

# /dna — il genetista al lavoro

Sei il genetista (identità: `${CLAUDE_PLUGIN_ROOT}/AGENT.md` — guardrail inclusi).
**Repo dati:** directory corrente. Raw assente → intake (sezione Setup dell'AGENT.md).

## Strumenti (tutti in `${CLAUDE_PLUGIN_ROOT}/scripts/`, eseguiti dal repo dati)

| Bisogno | Comando |
|---|---|
| Nuovo file raw | `python3.12 .../dna_ingest.py data/dna/raw/<file>` |
| (Ri)annotare uno strato | `python3.12 .../dna_annotate.py --layer panels\|clinvar\|gwas\|pharmgkb [--update-db]` |
| Rigenerare kb + report | `python3.12 .../dna_report.py` |
| Genotipo/annotazioni puntuali | `python3.12 .../dna_query.py rs4680 [--web]` o `--gene COMT` |
| Domande SQL fuori schema | server MCP sqlite su `data/dna/genotypes.db` |

## Flusso di risposta

1. Domanda puntuale → `dna_query` (o SQL) + interpretazione dai pannelli e dalla tua conoscenza; cita genotipo E fonte/versione.
2. Domanda di pathway → leggi `kb/genomica.md` (se stantio: rigenera).
3. Hit clinica (ClinVar) → SEMPRE col disclaimer del report; mai annunci.
4. Farmaci → "da discutere con il medico che prescrive", sempre.
5. Scoperte nuove → skill `propagate` del core.

Mai JSON a schermo. Mai determinismo genetico: predisposizione ≠ destino.
```

- [ ] **Step 2: AGENT.md — aggiungere sezione "## Strumenti (pipeline deterministica)"** con la stessa tabella comandi della skill (il genetista la conosce anche fuori dalla skill) e la regola: "i numeri ufficiali escono dagli script, mai dalla tua memoria del raw".

- [ ] **Step 3: plugin.json con MCP**

```json
{
  "name": "genomics",
  "description": "Genomica — pipeline deterministica sul raw DNA dell'utente (ingest, annotazione ClinVar/PharmGKB/GWAS/pannelli, report) + query via CLI e MCP. Mai determinismo genetico.",
  "version": "0.2.0",
  "author": {"name": "Francesco Mondora"},
  "mcpServers": {
    "dna-sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "data/dna/genotypes.db"]
    }
  }
}
```

- [ ] **Step 4: marketplace.json** — aggiornare la description del plugin genomics alla stessa del plugin.json; `metadata.version` → `0.8.0`.

- [ ] **Step 5: Verifica manuale** — `python3.12 -m json.tool genomics/.claude-plugin/plugin.json && python3.12 -m json.tool .claude-plugin/marketplace.json` → JSON validi. Suite completa: `python3.12 -m pytest genomics/scripts/tests/ -v` → tutta verde.

- [ ] **Step 6: Commit** (`feat(genomics): skill /dna, strumenti in AGENT.md, MCP sqlite nel manifest` + firma)

---

### Task 13: Verifica reale sul repo dati di Francesco (fuori dal plugin)

**Files:** nessuna modifica al plugin; opera in `/Users/fmondora/wip/personal/lucia`.

- [ ] **Step 1: Push + update**: `git push`, `claude plugin marketplace update wellness-agents`, `claude plugin update genomics@wellness-agents`.
- [ ] **Step 2: Ingest reale**: da `/Users/fmondora/wip/personal/lucia`: `mkdir -p data/dna/raw && cp docs/raw/genome_*.xlsx data/dna/raw/` poi `python3.12 ~/.claude/plugins/cache/wellness-agents/genomics/*/scripts/dna_ingest.py data/dna/raw/genome_*.xlsx`. Expected: `inserted` ≈ 630k, `skipped_nocall` > 0.
- [ ] **Step 3: Spot-check contro il kb curato a mano** (validazione d'oro): `dna_query.py rs1801133`, `rs4680`, `rs2243250`, `rs20541` — i genotipi DEVONO coincidere con la tabella storica di `kb/genomica.md` (prima della rigenerazione!). Se uno non coincide: STOP, indagare (strand? colonna xlsx?) prima di procedere.
- [ ] **Step 4: Annotate panels + report**: `dna_annotate.py --layer panels` poi `dna_report.py --layer panels`. Confrontare il nuovo `kb/genomica.md` con il vecchio (git diff nel repo lucia): i genotipi devono coincidere riga per riga sui pathway coperti.
- [ ] **Step 5: Strati esterni** (richiedono download, si fanno quando Francesco vuole): `--layer clinvar --update-db`, `--layer gwas --update-db`, dump PharmGKB manuale poi `--layer pharmgkb`. Report finali: `dna_report.py`.
- [ ] **Step 6:** Aggiornare `memory/agents/` nota del genetista nel repo lucia (entry: pipeline attiva, versioni DB usate, esito spot-check).

---

## Self-review (fatta in scrittura)

- **Copertura spec**: ingest 3 formati (T2-3) ✓ · 4 strati (T4-7) ✓ · report+disclaimer (T8) ✓ · query+--web (T9) ✓ · MCP (T12) ✓ · pannelli (T4, T11) ✓ · determinismo (T10) ✓ · error handling build/no-call/dump mancante (T2, T5, T7) ✓ · fixture sintetiche (tutte) ✓ · verifica reale (T13) ✓.
- **Tipi coerenti**: `ingest()->dict`, `annotate_*()->int`, `report_*()->Path`, `lookup()->dict` usati coerentemente nei task successivi.
- **Nessun placeholder**: ogni step con codice ha il codice; il Task 11 è contenuto editoriale con metodo e validazione espliciti.
