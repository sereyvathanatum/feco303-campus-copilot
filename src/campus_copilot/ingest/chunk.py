"""Stage 4, chunk.

PDF: page-aware, split within a page and never across pages.
Markdown: header-aware; `MarkdownHeaderTextSplitter` on `#`-`###` gives a section
path such as "Library rules › Loans", then a size-bounded recursive split inside
each section. Size is measured in tokens by default (`rag.length_unit`).
"""

from __future__ import annotations

import hashlib
import statistics

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from ..config import Profile
from .extract import detect_script
from .tokens import TokenCounter, char_counter, get_counter

SEPARATORS = ["\n\n", "\n- ", ". ", "។", "\n", " ", ""]  # U+17D4 is the Khmer full stop
ORPHAN_TOKENS = 25
SECTION_SEP = " › "  # " › "


def chunk_id(source_id: str, locator: str, text: str) -> str:
    return hashlib.sha256(f"{source_id}|{locator}|{text}".encode("utf-8")).hexdigest()[:16]


def chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def counters(profile: Profile, embed_model: str) -> tuple[TokenCounter, TokenCounter]:
    """(length counter used for sizing, token counter used for reporting)."""
    tokens = get_counter(str(profile.get("rag.tokenizer", "auto")), embed_model)
    sizing = char_counter() if profile.get("rag.length_unit", "tokens") == "chars" else tokens
    return sizing, tokens


def _splitter(profile: Profile, sizing: TokenCounter) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=int(profile.get("rag.chunk_size", 220)),
        chunk_overlap=int(profile.get("rag.chunk_overlap", 30)),
        length_function=sizing.count,
        separators=SEPARATORS,
        keep_separator="end",
    )


def _language(doc_language: str, text: str) -> str:
    script = detect_script(text)
    if script == "khmer":
        return "km"
    if doc_language in {"en", "km"}:
        return doc_language if not (doc_language == "km" and script == "latin") else "en"
    return "en" if script == "latin" else doc_language


def _section_path(meta: dict, title: str) -> str:
    parts = [meta[k] for k in ("h1", "h2", "h3") if meta.get(k)]
    if len(parts) > 1:
        parts = parts[1:]  # the document title is already the source; keep the path below it
    return SECTION_SEP.join(parts) or title


def chunk(units: list[dict], manifest: list[dict], profile: Profile, embed_model: str) -> tuple[list[dict], dict]:
    sizing, tokens = counters(profile, embed_model)
    splitter = _splitter(profile, sizing)
    docs = {d["source_id"]: d for d in manifest}
    header_split = profile.get("ingest.markdown_split", "headers+tokens") == "headers+tokens"
    md_headers = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False)
    chunks: list[dict] = []
    positions: dict[str, int] = {}

    def add(source_id: str, page, section, text: str) -> None:
        text = text.strip()
        if not text:
            return
        position = positions.get(source_id, 0)
        positions[source_id] = position + 1
        locator = f"p{page}" if page is not None else f"s:{section}"
        chunks.append({
            "chunk_id": chunk_id(source_id, locator, text), "chunk_hash": chunk_hash(text), "source_id": source_id,
            "page": page, "section": section, "text": text, "token_count": tokens.count(text),
            "length": sizing.count(text), "position": position,
            "language": _language(docs.get(source_id, {}).get("language", "unknown"), text),
        })

    for unit in units:
        doc = docs.get(unit["source_id"], {})
        if unit["format"] == "pdf":
            for piece in merge_small(splitter.split_text(unit["text"]), tokens):
                add(unit["source_id"], unit["page"], None, piece)
        elif header_split:
            carry = ""
            sections = md_headers.split_text(unit["text"])
            for index, section_doc in enumerate(sections):
                content = f"{carry}\n\n{section_doc.page_content}".strip() if carry else section_doc.page_content
                last = index == len(sections) - 1
                # A section that is only a heading and a banner line joins the next section.
                if tokens.count(content) < ORPHAN_TOKENS and not last:
                    carry = content
                    continue
                carry = ""
                section = _section_path(section_doc.metadata, doc.get("title", unit["source_id"]))
                for piece in merge_small(splitter.split_text(content), tokens):
                    add(unit["source_id"], None, section, piece)
        else:
            for piece in merge_small(splitter.split_text(unit["text"]), tokens):
                add(unit["source_id"], None, doc.get("title", unit["source_id"]), piece)
    return chunks, chunk_report(chunks, profile, tokens, sizing)


def merge_small(pieces: list[str], tokens: TokenCounter) -> list[str]:
    """Join a piece shorter than ORPHAN_TOKENS onto its neighbour inside the same page or section."""
    out: list[str] = []
    for piece in pieces:
        if out and (tokens.count(piece) < ORPHAN_TOKENS or tokens.count(out[-1]) < ORPHAN_TOKENS):
            out[-1] = out[-1].rstrip() + "\n" + piece.lstrip()
        else:
            out.append(piece)
    return out


def window_check(chunks: list[dict], limit: int, tokens: TokenCounter) -> list[dict]:
    over = []
    for c in chunks:
        if c["token_count"] > limit:
            kept, dropped = tokens.split_at(c["text"], limit)
            over.append({"chunk_id": c["chunk_id"], "source_id": c["source_id"], "page": c["page"],
                         "section": c["section"], "token_count": c["token_count"],
                         "dropped_tokens": c["token_count"] - limit, "dropped_text": dropped})
    return over


def _spread(values: list[int]) -> dict:
    if not values:
        return {}
    return {"n": len(values), "min": min(values), "median": statistics.median(values), "max": max(values),
            "mean": round(statistics.fmean(values), 1)}


def chunk_report(chunks: list[dict], profile: Profile, tokens: TokenCounter, sizing: TokenCounter) -> dict:
    limit = int(profile.get("rag.embed_max_tokens", 32768))
    languages = sorted({c["language"] for c in chunks})
    return {
        "chunks": len(chunks),
        "length_unit": profile.get("rag.length_unit", "tokens"),
        "chunk_size": profile.get("rag.chunk_size"), "chunk_overlap": profile.get("rag.chunk_overlap"),
        "tokenizer": tokens.label, "sizing": sizing.label,
        "token_spread": {lang: _spread([c["token_count"] for c in chunks if c["language"] == lang]) for lang in languages},
        "char_spread": {lang: _spread([len(c["text"]) for c in chunks if c["language"] == lang]) for lang in languages},
        "embed_window": limit,
        "over_window": window_check(chunks, limit, tokens),
        "orphans": [{"chunk_id": c["chunk_id"], "source_id": c["source_id"], "token_count": c["token_count"]}
                    for c in chunks if c["token_count"] < ORPHAN_TOKENS],
        "pdf_chunks_crossing_pages": 0,  # impossible by construction: PDF text is split per page
    }
