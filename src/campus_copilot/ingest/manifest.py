"""Document manifests: `data/sources/manifest.csv` (pack, committed) and `data/inbox/manifest.csv` (local)."""

from __future__ import annotations

import csv
import datetime as dt
import re
import shutil
from pathlib import Path

from ..config import DATA_DIR, REPO_ROOT

COLUMNS = ["source_id", "file", "format", "title", "language", "licence", "origin", "added"]
PACK_MANIFEST = DATA_DIR / "sources" / "manifest.csv"
INBOX = DATA_DIR / "inbox"
INBOX_MANIFEST = INBOX / "manifest.csv"
SUPPORTED = {".pdf": "pdf", ".md": "md", ".markdown": "md"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "document"


def read_manifest(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in COLUMNS})


def manifest_for(folder: Path) -> Path:
    return folder / "manifest.csv"


def rows_by_file(folder: Path) -> dict[str, dict]:
    return {row["file"]: row for row in read_manifest(manifest_for(folder))}


def add_document(src: Path, licence: str, origin: str = "", title: str = "", language: str = "",
                 source_id: str = "") -> dict:
    """Copy a document into `data/inbox/` and record it in the inbox manifest."""
    fmt = SUPPORTED.get(src.suffix.lower())
    if fmt is None:
        raise ValueError(f"unsupported format {src.suffix!r}: only PDF and Markdown are ingested")
    INBOX.mkdir(parents=True, exist_ok=True)
    target = INBOX / src.name
    if src.resolve() != target.resolve():
        shutil.copyfile(src, target)
    rows = [r for r in read_manifest(INBOX_MANIFEST) if r["file"] != target.name]
    row = {"source_id": source_id or slugify(src.stem), "file": target.name, "format": fmt,
           "title": title or src.stem, "language": language or "unknown", "licence": licence or "unknown",
           "origin": origin or "added with cli ingest add", "added": dt.date.today().isoformat()}
    rows.append(row)
    write_manifest(INBOX_MANIFEST, rows)
    return row


def download_document(url: str, licence: str, origin: str = "", contact: str = "") -> dict:
    import requests

    name = Path(url.split("?")[0]).name or "download.pdf"
    if Path(name).suffix.lower() not in SUPPORTED:
        name += ".pdf"
    response = requests.get(url, timeout=30,
                            headers={"User-Agent": f"FECO303-CampusCopilot/1.0 (+{contact or 'helpdesk@example.edu'})"})
    response.raise_for_status()
    INBOX.mkdir(parents=True, exist_ok=True)
    target = INBOX / name
    target.write_bytes(response.content)
    return add_document(target, licence=licence, origin=origin or url)


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
