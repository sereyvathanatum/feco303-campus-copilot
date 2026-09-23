"""Stage 2, extract: PDF text per page (1-based `page`) and Markdown bodies with frontmatter metadata."""

from __future__ import annotations

import re

from ..config import REPO_ROOT
from .gather import read_frontmatter

KHMER = re.compile(r"[ក-៿]")
LATIN = re.compile(r"[A-Za-z]")
NEAR_EMPTY = 60


def detect_script(text: str) -> str:
    khmer, latin = len(KHMER.findall(text)), len(LATIN.findall(text))
    if khmer == 0 and latin == 0:
        return "none"
    return "khmer" if khmer >= latin else "latin"


def _khmer_noise_share(text: str) -> float:
    """Share of ASCII symbols wedged between Khmer characters: a sign of broken glyph order."""
    khmer = len(KHMER.findall(text))
    if not khmer:
        return 0.0
    wedged = len(re.findall(r"(?<=[ក-៿])[!-/:-@\[-`{-~A-Za-z]+(?=[ក-៿])", text))
    return round(wedged / khmer, 4)


def extract_pdf(doc: dict) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(REPO_ROOT / doc["file"]))
    units = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        script = detect_script(text)
        flags = []
        stripped = text.strip()
        if len(stripped) < NEAR_EMPTY:
            flags.append("empty or near-empty page (a scanned PDF has no text layer; OCR is out of scope)")
        replacement = text.count("�") / max(1, len(text))
        if replacement > 0.01:
            flags.append(f"replacement characters: {replacement:.1%}")
        noise = _khmer_noise_share(text)
        if script == "khmer":
            flags.append("Khmer script: PDF extraction of complex scripts is unreliable; Markdown is the source of truth")
        if noise > 0.02:
            flags.append(f"Khmer glyph-order noise: {noise:.1%} of Khmer characters have stray ASCII between them")
        units.append({"source_id": doc["source_id"], "format": "pdf", "page": number, "section": None,
                      "text": text, "chars": len(text), "script": script, "replacement_share": round(replacement, 4),
                      "khmer_noise_share": noise, "flags": flags})
    return units


def extract_markdown(doc: dict) -> list[dict]:
    raw = (REPO_ROOT / doc["file"]).read_text(encoding="utf-8", errors="replace")
    meta, body = read_frontmatter(raw)
    script = detect_script(body)
    flags = [] if body.strip() else ["empty document"]
    return [{"source_id": doc["source_id"], "format": "md", "page": None, "section": None, "text": body,
             "chars": len(body), "script": script, "metadata": meta,
             "replacement_share": round(body.count("�") / max(1, len(body)), 4), "flags": flags}]


def extract(manifest: list[dict]) -> tuple[list[dict], dict]:
    units: list[dict] = []
    for doc in manifest:
        if doc["status"] not in {"new", "changed"}:
            continue
        units.extend(extract_pdf(doc) if doc["format"] == "pdf" else extract_markdown(doc))
    stats = {
        "units": len(units),
        "pdf_pages": sum(1 for u in units if u["format"] == "pdf"),
        "markdown_files": sum(1 for u in units if u["format"] == "md"),
        "scripts": {s: sum(1 for u in units if u["script"] == s) for s in ("latin", "khmer", "none")},
        "flagged": [{"source_id": u["source_id"], "page": u["page"], "flags": u["flags"]} for u in units if u["flags"]],
    }
    return units, stats
