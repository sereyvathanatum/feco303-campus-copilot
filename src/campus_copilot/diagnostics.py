"""`cli check`: run mode, `.env` path, model IDs, and reachability per external service.

Keys are never printed; only their state (set, missing, placeholder).
"""

from __future__ import annotations

import os
import sqlite3
import time

from .config import Settings, is_real_key

MODE_MATRIX = [
    ("offline", "none", "none; stubs + fixtures"),
    ("nim", "NIM and/or Gemini key", "LLM, embeddings, reranker, VLM; stub decider"),
    ("full", "NIM and/or Gemini + Laya", "everything; Laya runs locally (no key); APIs live or fixture-cached"),
]

ENDPOINTS = {
    "NVIDIA NIM": "https://integrate.api.nvidia.com/v1/models",
    "Google AI Studio": "https://generativelanguage.googleapis.com/v1beta/openai/models",
    "Hugging Face (Laya)": "https://huggingface.co/api/models/convaiinnovations/laya",
    "Open-Meteo": "https://api.open-meteo.com/v1/forecast?latitude=11.56&longitude=104.93&hourly=precipitation_probability&forecast_days=1",
    "ExchangeRate-API": "https://open.er-api.com/v6/latest/USD",
    "Open Library": "https://openlibrary.org/search.json?q=isbn:9780262046305&limit=1",
    "Wikipedia REST": "https://en.wikipedia.org/api/rest_v1/page/summary/Transformer_(deep_learning)",
}


def key_state(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return "missing"
    return "set" if is_real_key(raw) else "placeholder (counts as missing)"


def probe(url: str, timeout: float = 4.0) -> tuple[str, float]:
    import requests

    started = time.perf_counter()
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "FECO303-CampusCopilot/1.0 (check)"})
        status = f"reachable (HTTP {response.status_code})"
    except requests.RequestException as exc:
        status = f"unreachable ({type(exc).__name__})"
    return status, (time.perf_counter() - started) * 1000


def storage_features() -> dict[str, str]:
    features: dict[str, str] = {}
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        features["SQLite FTS5"] = "available"
    except sqlite3.OperationalError:
        features["SQLite FTS5"] = "missing: lexical search falls back to the hashing encoder"
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        version = conn.execute("select vec_version()").fetchone()[0]
        features["sqlite-vec"] = f"available ({version})"
    except (ImportError, AttributeError, sqlite3.OperationalError) as exc:
        features["sqlite-vec"] = (f"unavailable ({type(exc).__name__}): this Python build blocks SQLite "
                                  "extensions; a Python from python.org or Homebrew loads them")
    finally:
        conn.close()
    try:
        import chromadb  # noqa: F401

        features["Chroma"] = "available (optional extra)"
    except ImportError:
        features["Chroma"] = "not installed (optional: pip install -r requirements-optional.txt)"
    return features


def laya_line(settings: Settings) -> str:
    """Where Laya runs and whether it can: the package in-process, a `laya-serve` URL, or off."""
    model = settings.decision_model
    if settings.offline_forced:
        return f"Laya {model} (not used: the profile forces offline mode; stub decider)"
    if settings.laya_mode == "off":
        return "stub decider (LAYA_MODE=off)"
    if settings.laya_mode == "http":
        return f"Laya {model} via laya-serve at {settings.laya_base_url} (LAYA_MODE=http)"
    if not settings.has_laya:
        return "stub decider (the laya package is not installed: pip install laya)"
    try:
        from importlib.metadata import version

        installed = version("laya")
    except Exception:
        installed = "?"
    return f"Laya {model} in-process (laya {installed}, device {settings.laya_device or 'auto'}; LAYA_MODE=local)"


def run_check(settings: Settings, network: bool = True) -> str:
    lines = ["Campus Copilot check", ""]
    lines.append("Run modes:")
    for mode, keys, live in MODE_MATRIX:
        marker = "->" if mode == settings.run_mode else "  "
        lines.append(f"  {marker} {mode:<8} keys: {keys:<24} live: {live}")
    lines.append("")
    lines.append(f"Run mode:  {settings.run_mode}")
    lines.append(f"Profile:   {settings.profile.name}  (capabilities: {', '.join(settings.profile.capabilities)})")
    lines.append(f".env file: {settings.env_file or 'not found (all keys missing; offline mode)'}")
    lines.append(f"NVIDIA_API_KEY:   {key_state('NVIDIA_API_KEY')}")
    lines.append(f"NVIDIA_NEMOTRON_API_KEY: {key_state('NVIDIA_NEMOTRON_API_KEY')} (optional; falls back to NVIDIA_API_KEY)")
    lines.append(f"GEMINI_API_KEY:   {key_state('GEMINI_API_KEY')} (optional; Google AI Studio chat provider)")
    lines.append(f"HF_TOKEN:         {key_state('HF_TOKEN')} (optional; tokenizer downloads)")
    if settings.profile.get("app.force_offline"):
        lines.append("Profile forces offline mode (app.force_offline = true).")
    for note in settings.notes:
        lines.append(f"Note: {note}")
    lines.append("")
    lines.append("Models:")
    providers = settings.chat_providers() or ["stub"]
    lines.append(f"  chat provider : {' -> '.join(providers)} (COPILOT_CHAT_PROVIDER={settings.chat_provider})")
    if settings.has_google:
        lines.append(f"  google chat   : {settings.google_chat_model}  small: {settings.google_small_model}")
    lines.append(f"  nim chat      : {settings.chat_model}")
    lines.append(f"  nim small     : {settings.small_model}")
    lines.append(f"  embeddings    : {settings.embed_model}")
    lines.append(f"  reranker      : {settings.rerank_model}")
    lines.append(f"  decision model: {laya_line(settings)}")
    lines.append("")
    lines.append("Storage features:")
    for name, state in storage_features().items():
        lines.append(f"  {name:<12}: {state}")
    lines.append("")
    lines.append(f"Public APIs: {'live' if settings.use_live_apis else 'recorded fixtures'}")
    if network:
        lines.append("Reachability:")
        for name, url in ENDPOINTS.items():
            status, ms = probe(url)
            lines.append(f"  {name:<16}: {status}, {ms:.0f} ms")
    else:
        lines.append("Reachability: skipped (--no-network)")
    return "\n".join(lines)
