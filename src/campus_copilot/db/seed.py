"""Deterministic campus-database seed from `data/seed/*.csv`."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from ..config import DATA_DIR

SCHEMA = Path(__file__).with_name("schema.sql")
SEED_DIR = DATA_DIR / "seed"

# Insert order respects foreign keys.
TABLES = ["accounts", "courses", "enrollments", "rooms", "sessions", "room_bookings",
          "books", "loans", "holds", "assignments", "events"]
INTEGER_COLUMNS = {"credits", "capacity", "has_projector", "has_pcs", "year", "copies_total", "returned"}
REAL_COLUMNS = {"weight"}


def _convert(column: str, value: str):
    if value == "":
        return None
    if column in INTEGER_COLUMNS:
        return int(value)
    if column in REAL_COLUMNS:
        return float(value)
    return value


def build(path: Path, seed_dir: Path = SEED_DIR) -> Path:
    """Create a fresh database at `path` from the schema and the seed CSV files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        for table in TABLES:
            with (seed_dir / f"{table}.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames or []
                quoted = ", ".join(f'"{c}"' for c in columns)
                marks = ", ".join("?" for _ in columns)
                rows = [tuple(_convert(c, row[c]) for c in columns) for row in reader]
            conn.executemany(f"INSERT INTO {table} ({quoted}) VALUES ({marks})", rows)
        conn.commit()
    finally:
        conn.close()
    return path


def content_hash(path: Path) -> str:
    """SHA-256 over every table's rows in rowid order; equal seeds give equal hashes."""
    digest = hashlib.sha256()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        for table in TABLES:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            digest.update(table.encode())
            digest.update(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
    finally:
        conn.close()
    return digest.hexdigest()


def table_counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        conn.close()
