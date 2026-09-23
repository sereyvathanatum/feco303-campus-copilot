"""Stage 1, gather: scan source folders, hash files, compare with the knowledge base, flag problems."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ..config import DATA_DIR, REPO_ROOT, Profile
from . import manifest as mf
from .store import documents

SKIP_NAMES = {"manifest.csv", "README.md", "probes.jsonl", "probes.generated.jsonl"}
MAX_BYTES = 20 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def read_frontmatter(text: str) -> tuple[dict, str]:
    """Split simple YAML frontmatter (`key: value` lines) from a Markdown body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"').strip("'")
    body = text[end + 4:].lstrip("\n")
    return meta, body


def pdf_pages(path: Path) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def source_folders(profile: Profile) -> list[Path]:
    folders = [REPO_ROOT / p for p in profile.get("ingest.sources", ["data/sources", "data/inbox"])]
    if profile.get("data.include_adversarial", False):
        folders.append(DATA_DIR / "sources_adversarial")
    return folders


def gather(conn: sqlite3.Connection, profile: Profile) -> tuple[list[dict], dict]:
    known = documents(conn)
    records: list[dict] = []
    skipped: list[dict] = []
    seen_hash: dict[str, str] = {}
    include_pdf = bool(profile.get("data.include_pdf", True))
    for folder in source_folders(profile):
        if not folder.is_dir():
            continue
        rows = mf.rows_by_file(folder)
        inbox_new_rows = []
        for path in sorted(p for p in folder.iterdir() if p.is_file()):
            if path.name in SKIP_NAMES or path.name.startswith("."):
                continue
            fmt = mf.SUPPORTED.get(path.suffix.lower())
            if fmt is None:
                skipped.append({"file": mf.relpath(path), "reason": f"unsupported format {path.suffix or '(none)'}"})
                continue
            if fmt == "pdf" and not include_pdf:
                skipped.append({"file": mf.relpath(path), "reason": "PDF excluded by profile (data.include_pdf = false)"})
                continue
            row = dict(rows.get(path.name, {}))
            meta = {}
            if fmt == "md":
                meta, _ = read_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            flags = []
            if not row:
                row = {"source_id": meta.get("source_id") or mf.slugify(path.stem), "file": path.name, "format": fmt,
                       "title": meta.get("title") or path.stem, "language": meta.get("language", "unknown"),
                       "licence": meta.get("licence", "unknown"), "origin": meta.get("origin", ""),
                       "added": ""}
                flags.append("not in manifest: registered automatically")
                if folder == mf.INBOX:
                    inbox_new_rows.append(row)
            digest = sha256_file(path)
            size = path.stat().st_size
            pages = pdf_pages(path) if fmt == "pdf" else None
            licence = (row.get("licence") or "unknown").strip()
            if licence.lower() == "unknown" or not licence:
                flags.append("licence unknown")
            if not (row.get("origin") or "").strip():
                flags.append("origin missing")
            if digest in seen_hash:
                flags.append(f"duplicate of {seen_hash[digest]} (same SHA-256)")
            seen_hash.setdefault(digest, row["source_id"])
            if size > MAX_BYTES:
                flags.append(f"large file ({size // 1024 // 1024} MB)")
            if fmt == "pdf" and not pages:
                flags.append("no readable pages")
            prior = known.get(row["source_id"])
            if prior and prior["status"] == "excluded":
                has_chunks = conn.execute("SELECT 1 FROM chunks WHERE source_id = ? LIMIT 1",
                                          (row["source_id"],)).fetchone()
                status = "removed" if has_chunks else "excluded"
                flags.append("excluded with cli ingest --remove")
            elif prior is None or prior["status"] == "removed":
                status = "new"
            elif prior["sha256"] != digest:
                status = "changed"
            else:
                status = "unchanged"
            records.append({
                "source_id": row["source_id"], "file": mf.relpath(path), "format": fmt,
                "title": row.get("title") or path.stem, "language": row.get("language") or "unknown",
                "licence": licence or "unknown", "origin": row.get("origin", ""), "added": row.get("added", ""),
                "sha256": digest, "bytes": size, "pages": pages, "status": status, "flags": flags,
            })
        if inbox_new_rows:
            existing = mf.read_manifest(mf.INBOX_MANIFEST)
            mf.write_manifest(mf.INBOX_MANIFEST, existing + inbox_new_rows)
    seen = {r["source_id"] for r in records}
    for source_id, prior in known.items():
        has_chunks = conn.execute("SELECT 1 FROM chunks WHERE source_id = ? LIMIT 1", (source_id,)).fetchone()
        if source_id not in seen and (prior["status"] == "ingested" or (prior["status"] == "excluded" and has_chunks)):
            records.append({**{k: prior.get(k) for k in ("source_id", "file", "format", "title", "language",
                                                           "licence", "origin", "sha256", "pages")},
                            "bytes": 0, "added": "", "status": "removed",
                            "flags": ["file no longer present" if prior["status"] == "ingested" else "excluded"]})
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    stats = {"documents": len(records), "by_status": counts, "skipped": skipped,
             "flagged": {r["source_id"]: r["flags"] for r in records if r["flags"]},
             "by_format": {f: sum(1 for r in records if r["format"] == f) for f in ("pdf", "md")}}
    return records, stats
