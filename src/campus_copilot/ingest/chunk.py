"""Stage 4, chunk.

PDF: page-aware, split within a page and never across pages.
Markdown: header-aware; `MarkdownHeaderTextSplitter` on `#`-`####` gives a section
path such as "Library rules › Loans", then a size-bounded recursive split inside
each section. Size is measured in tokens by default (`rag.length_unit`).
Tables (`ingest.tables`, see `tables.py`) are split only between rows, and every piece
repeats the header row, so no chunk holds numbers without their column names.
Context header (`ingest.context_header`): each Markdown chunk starts with a breadcrumb line
"# Document title › Section › Subsection", so a continuation chunk still says what it is
about ("IV. Tuition Fees › A) Bachelor's Degree", not only "A) Bachelor's Degree"). The
breadcrumb is part of the chunk text: it is embedded, indexed by FTS5, and shown to the model.
"""

from __future__ import annotations

import hashlib
import re
import statistics

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from ..config import Profile
from . import tables
from .extract import detect_script
from .tokens import TokenCounter, char_counter, get_counter

# Regex separators, tried in order. A list item is split at the newline before its marker (a lookahead),
# so the marker stays with its item instead of dangling at the end of the previous piece.
# U+17D4 is the Khmer full stop.
SEPARATORS = [r"\n\n", r"\n(?=[-*•] |\d{1,2}[.)] )", r"\. ", "។", r"\n", " ", ""]
ORPHAN_TOKENS = 25
SECTION_SEP = " › "  # " › "
HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
HEADING_LINE = re.compile(r"^#{1,6}\s+(.*?)\s*$")


# Bump when the chunking rules change, so `cli ingest` re-chunks documents whose files did not change.
CHUNKER_VERSION = 2  # 2: row-wise tables, context header, heading levels, list-item boundaries
RECIPE_KEYS = ("rag.chunk_size", "rag.chunk_overlap", "rag.length_unit", "rag.tokenizer", "ingest.markdown_split",
               "ingest.tables", "ingest.context_header", "ingest.clean.strip_headers")


def recipe(profile: Profile) -> str:
    """Fingerprint of everything that shapes chunks besides the file itself (stored per document)."""
    parts = [f"v{CHUNKER_VERSION}"] + [f"{key}={profile.get(key)}" for key in RECIPE_KEYS]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


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
        is_separator_regex=True,
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
    parts = [" ".join(meta[k].split()) for k in ("h1", "h2", "h3", "h4") if meta.get(k)]
    if meta.get("h1") and len(parts) > 1:
        parts = parts[1:]  # the `#` heading is the document title, already the source; keep the path below it
    return SECTION_SEP.join(parts) or title


def breadcrumb(title: str, section: str | None) -> str:
    parts = [title] + (section.split(SECTION_SEP) if section else [])
    return "# " + SECTION_SEP.join(dict.fromkeys(p.strip() for p in parts if p and p.strip()))


def with_context(text: str, title: str, section: str | None) -> str:
    """Prefix the breadcrumb; heading lines that the breadcrumb already names are dropped."""
    path = {" ".join(p.split()) for p in [title] + (section.split(SECTION_SEP) if section else [])}
    kept = []
    for line in text.strip().split("\n"):
        heading = HEADING_LINE.match(line.strip())
        if heading and " ".join(heading.group(1).split()) in path:
            continue
        kept.append(line)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return breadcrumb(title, section) + "\n" + body


def split_section(content: str, splitter, sizing: TokenCounter, budget: int, fmt: str,
                  state: dict | None = None) -> list[str]:
    """Plain text through the recursive splitter; tables split between rows with the header repeated.

    `state["table"]` carries the last table of the document into the next section, so a table cut at a
    page break (and so under the next heading) can still take its header from the part before the cut.
    """
    if fmt == "text":
        return splitter.split_text(content)
    state = state if state is not None else {}
    out: list[str] = []
    for kind, block in tables.find_blocks(content, state.get("table")):
        if kind == "table":
            state["table"] = block
            out.extend(tables.pieces(block, budget, sizing.count, fmt))
        else:
            out.extend(splitter.split_text(block))
    return out


def chunk(units: list[dict], manifest: list[dict], profile: Profile, embed_model: str) -> tuple[list[dict], dict]:
    sizing, tokens = counters(profile, embed_model)
    splitter = _splitter(profile, sizing)
    docs = {d["source_id"]: d for d in manifest}
    header_split = profile.get("ingest.markdown_split", "headers+tokens") == "headers+tokens"
    table_format = str(profile.get("ingest.tables", "markdown"))
    if table_format not in tables.FORMATS:
        raise ValueError(f"ingest.tables must be one of {', '.join(tables.FORMATS)}, not {table_format!r}")
    context = str(profile.get("ingest.context_header", "markdown"))
    budget = int(profile.get("rag.chunk_size", 220))
    md_headers = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS, strip_headers=False)
    chunks: list[dict] = []
    positions: dict[str, int] = {}

    def add(source_id: str, page, section, text: str) -> None:
        text = "\n".join(line.rstrip() for line in text.strip().split("\n"))  # the header splitter ends lines with "  "
        if not text:
            return
        title = docs.get(source_id, {}).get("title") or source_id
        if context == "all" or (context == "markdown" and page is None):
            text = with_context(text, title if page is None else f"{title}, page {page}", section)
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
            state: dict = {}
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
                pieces = split_section(content, splitter, sizing, budget, table_format, state)
                for piece in merge_small(pieces, tokens):
                    add(unit["source_id"], None, section, piece)
        else:
            pieces = split_section(unit["text"], splitter, sizing, budget, table_format)
            for piece in merge_small(pieces, tokens):
                add(unit["source_id"], None, doc.get("title", unit["source_id"]), piece)
    return chunks, chunk_report(chunks, profile, tokens, sizing)


def merge_small(pieces: list[str], tokens: TokenCounter) -> list[str]:
    """Join a piece shorter than ORPHAN_TOKENS onto its neighbour inside the same page or section.

    A heading line or a short lead-in ("See the tuition fees below:") joins the table piece after it.
    """
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
