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
