"""Token counting for chunk sizing (docs/implementation-plan.md §8.4.2, stage 4).

Order of preference (`rag.tokenizer = auto`):

1. the embedder's published tokenizer from Hugging Face (`hf`);
2. `tiktoken` `cl100k_base`, labelled `approximate` (`tiktoken`);
3. a built-in approximate counter that needs no download (`builtin`).

`COPILOT_TOKENIZER` overrides the profile, which keeps tests deterministic.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

# Latin words in pieces of up to 4 letters, digit groups of up to 3, each Khmer code
# point, and each other visible character: roughly the granularity of a BPE tokenizer.
_BUILTIN = re.compile(r"[A-Za-zÀ-ɏ]{1,4}|\d{1,3}|[ក-៿᧠-᧿]|[^\s]")


@dataclass
class TokenCounter:
    name: str
    approximate: bool
    _count: Callable[[str], int]
    _split: Callable[[str, int], tuple[str, str]]

    def count(self, text: str) -> int:
        return self._count(text)

    def split_at(self, text: str, limit: int) -> tuple[str, str]:
        """Return (kept, dropped): what a truncating embedder with `limit` tokens keeps and loses."""
        return self._split(text, limit)

    @property
    def label(self) -> str:
        return f"{self.name}{' (approximate)' if self.approximate else ''}"


def _builtin() -> TokenCounter:
    def count(text: str) -> int:
        return sum(1 for _ in _BUILTIN.finditer(text))

    def split(text: str, limit: int) -> tuple[str, str]:
        for index, match in enumerate(_BUILTIN.finditer(text)):
            if index == limit:
                return text[: match.start()], text[match.start():]
        return text, ""

    return TokenCounter("builtin", True, count, split)


def _tiktoken() -> TokenCounter | None:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None

    def split(text: str, limit: int) -> tuple[str, str]:
        ids = enc.encode(text)
        if len(ids) <= limit:
            return text, ""
        kept = enc.decode(ids[:limit])
        return kept, text[len(kept):]

    return TokenCounter("tiktoken/cl100k_base", True, lambda t: len(enc.encode(t)), split)


def _huggingface(model_id: str) -> TokenCounter | None:
    try:
        from tokenizers import Tokenizer

        tok = Tokenizer.from_pretrained(model_id, token=os.environ.get("HF_TOKEN") or None)
    except Exception:
        return None

    def split(text: str, limit: int) -> tuple[str, str]:
        enc = tok.encode(text, add_special_tokens=False)
        if len(enc.ids) <= limit:
            return text, ""
        cut = enc.offsets[limit][0]
        return text[:cut], text[cut:]

    return TokenCounter(f"hf/{model_id}", False, lambda t: len(tok.encode(t, add_special_tokens=False).ids), split)


@lru_cache(maxsize=8)
def get_counter(preference: str = "auto", embed_model: str = "nvidia/nemotron-3-embed-1b") -> TokenCounter:
    preference = os.environ.get("COPILOT_TOKENIZER") or preference or "auto"
    if preference in {"auto", "hf"}:
        counter = _huggingface(embed_model)
        if counter:
            return counter
    if preference in {"auto", "hf", "tiktoken"}:
        counter = _tiktoken()
        if counter:
            return counter
    return _builtin()


def char_counter() -> TokenCounter:
    """Character "counter" for `rag.length_unit = chars` (E02 comparison)."""
    return TokenCounter("characters", False, len, lambda t, n: (t[:n], t[n:]))
