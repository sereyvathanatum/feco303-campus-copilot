"""Configuration: `.env` loading, placeholder detection, profiles, capabilities, run mode.

Loading rules (docs/implementation-plan.md §7.1):

1. `COPILOT_ENV_FILE` wins; otherwise `.env` is searched upward from the working
   directory, then the repository root is tried.
2. Variables already present in the process environment win over `.env` values.
3. A small built-in parser takes over when `python-dotenv` is missing.
4. Placeholder keys from `.env.example` count as missing.
"""

from __future__ import annotations

import copy
import datetime as dt
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = REPO_ROOT / "profiles"
DATA_DIR = REPO_ROOT / "data"
RUNS_DIR = REPO_ROOT / "runs"

PLACEHOLDER_KEYS = {
    "nvapi-replace-with-a-real-key",
    "laya-replace-with-a-real-key",
    "gemini-replace-with-a-real-key",
    "hf-replace-with-a-real-token",
}

ALL_CAPABILITIES = (
    "kb", "rag", "memory", "decisions", "tools", "agent", "writes",
    "mcp", "evaluation", "guards", "vision",
)

DEFAULTS = {
    "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
    "NIM_CHAT_MODEL": "google/gemma-4-31b-it",
    "NIM_SMALL_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "NIM_EMBED_MODEL": "nvidia/nemotron-3-embed-1b",
    "NIM_RERANK_MODEL": "nvidia/llama-nemotron-rerank-vl-1b-v2",  # the text-only 1b-v2 reached end of life on 2026-08-25
    "NIM_TEMPERATURE": "0.0",
    "NIM_MAX_TOKENS": "512",
    "NIM_TIMEOUT": "60",
    "GOOGLE_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
    "GOOGLE_CHAT_MODEL": "gemma-4-31b-it",
    "GOOGLE_SMALL_MODEL": "gemma-4-26b-a4b-it",
    "GOOGLE_TIMEOUT": "120",
    "COPILOT_CHAT_PROVIDER": "nim",
    "LAYA_MODE": "local",
    "LAYA_MODEL": "auto",
    "LAYA_DEVICE": "",
    "LAYA_BASE_URL": "http://127.0.0.1:8000/v1",
    "LAYA_TIMEOUT": "30",
    "COPILOT_PROFILE": "baseline",
    "COPILOT_APIS_LIVE": "true",
    "COPILOT_HTTP_CONTACT": "helpdesk@example.edu",
    "COPILOT_LIVE_TESTS": "0",
}


# --------------------------------------------------------------------------- .env

def _parse_env_file(path: Path) -> dict[str, str]:
    """Fallback parser: KEY=VALUE lines, `#` comments, optional quotes, `export ` prefix."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def find_env_file() -> Path | None:
    explicit = os.environ.get("COPILOT_ENV_FILE", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    try:
        from dotenv import find_dotenv

        found = find_dotenv(usecwd=True)
        if found:
            return Path(found)
    except ImportError:
        here = Path.cwd().resolve()
        for folder in (here, *here.parents):
            if (folder / ".env").is_file():
                return folder / ".env"
    root_env = REPO_ROOT / ".env"
    return root_env if root_env.is_file() else None


def load_env(path: Path | None = None) -> Path | None:
    """Load `.env` into `os.environ` without overriding existing variables."""
    path = path or find_env_file()
    if path is None:
        return None
    try:
        from dotenv import dotenv_values

        values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    except ImportError:
        values = _parse_env_file(path)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return path


def init_env_file() -> tuple[Path, bool]:
    """Copy `.env.example` to `.env` only when `.env` is absent. Returns (path, created)."""
    target = REPO_ROOT / ".env"
    if target.exists():
        return target, False
    target.write_text((REPO_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    return target, True


def is_real_key(value: str | None) -> bool:
    return bool(value and value.strip() and value.strip() not in PLACEHOLDER_KEYS)


# ----------------------------------------------------------------------- profiles

def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def profile_path(name: str) -> Path:
    name = name.removesuffix(".toml")
    path = PROFILES_DIR / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"profile not found: {path}")
    return path


def load_profile_dict(name: str, _seen: tuple[str, ...] = ()) -> dict:
    """Read a profile and merge it over its parent (`extends`, default `baseline`)."""
    if name in _seen:
        raise ValueError(f"profile inheritance loop: {' -> '.join((*_seen, name))}")
    with profile_path(name).open("rb") as handle:
        data = tomllib.load(handle)
    parent = data.pop("extends", None if name == "baseline" else "baseline")
    if parent:
        data = _deep_merge(load_profile_dict(parent, (*_seen, name)), data)
    return data


@dataclass
class Profile:
    name: str
    data: dict

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    @property
    def capabilities(self) -> tuple[str, ...]:
        caps = self.data.get("capabilities", list(ALL_CAPABILITIES))
        unknown = set(caps) - set(ALL_CAPABILITIES)
        if unknown:
            raise ValueError(f"unknown capabilities in profile {self.name}: {sorted(unknown)}")
        return tuple(caps)

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    @property
    def step(self) -> int | None:
        return self.data.get("step")


def load_profile(name: str | None = None, overrides: dict[str, Any] | None = None) -> Profile:
    name = name or os.environ.get("COPILOT_PROFILE") or DEFAULTS["COPILOT_PROFILE"]
    profile = Profile(name=name, data=load_profile_dict(name))
    for key, value in (overrides or {}).items():
        profile.set(key, value)
    return profile


def list_profiles() -> list[str]:
    return sorted(
        str(p.relative_to(PROFILES_DIR).with_suffix("")).replace("\\", "/")
        for p in PROFILES_DIR.rglob("*.toml")
    )


def step_profile_name(step: int) -> str:
    if not 1 <= step <= 12:
        raise ValueError("build-path steps run from 1 to 12")
    return f"steps/step-{step:02d}"


# ----------------------------------------------------------------------- settings

@dataclass
class Settings:
    env_file: Path | None
    nvidia_api_key: str | None
    nemotron_api_key: str | None
    gemini_api_key: str | None
    chat_provider: str
    google_base_url: str
    google_chat_model: str
    google_small_model: str
    google_timeout: float
    laya_api_key: str | None
    nvidia_base_url: str
    chat_model: str
    small_model: str
    embed_model: str
    rerank_model: str
    temperature: float
    max_tokens: int
    nim_timeout: float
    laya_mode: str
    laya_model: str
    laya_device: str
    laya_base_url: str
    laya_timeout: float
    apis_live: bool
    http_contact: str
    live_tests: bool
    profile: Profile
    notes: list[str] = field(default_factory=list)

    @property
    def offline_forced(self) -> bool:
        return bool(self.profile.get("app.force_offline", False))

    @property
    def has_nim(self) -> bool:
        return is_real_key(self.nvidia_api_key) and not self.offline_forced

    @property
    def has_google(self) -> bool:
        return is_real_key(self.gemini_api_key) and not self.offline_forced

    @property
    def has_live_llm(self) -> bool:
        return self.has_nim or self.has_google

    def chat_providers(self) -> list[str]:
        """Live chat providers in preference order: the selected one first, the other as fallback."""
        available = [p for p, ok in (("nim", self.has_nim), ("google", self.has_google)) if ok]
        return sorted(available, key=lambda p: p != self.chat_provider)

    @property
    def has_laya(self) -> bool:
        """Laya is usable: `LAYA_MODE=local` with the `laya` package installed, or `LAYA_MODE=http`."""
        if self.offline_forced or self.laya_mode == "off":
            return False
        if self.laya_mode == "http":
            return True
        import importlib.util

        return importlib.util.find_spec("laya") is not None

    @property
    def run_mode(self) -> str:
        # "nim" mode means live models (NIM, or Google AI Studio for chat) with the stub decider.
        if not self.has_live_llm:
            return "offline"
        return "full" if self.has_laya else "nim"

    @property
    def decision_model(self) -> str:
        """The Laya checkpoint: profile `laya.model`, then `LAYA_MODEL`; `auto` lets Laya's router pick by language."""
        return self.profile.get("laya.model") or self.laya_model or "auto"

    @property
    def use_live_apis(self) -> bool:
        return bool(self.profile.get("apis.live", True)) and self.apis_live and self.run_mode != "offline"


def _env(name: str) -> str:
    return os.environ.get(name, DEFAULTS.get(name, ""))


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_settings(profile: str | Profile | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    env_file = load_env()
    prof = profile if isinstance(profile, Profile) else load_profile(profile, overrides)
    notes: list[str] = []
    nv, laya_key = os.environ.get("NVIDIA_API_KEY"), os.environ.get("LAYA_API_KEY")
    nemo = os.environ.get("NVIDIA_NEMOTRON_API_KEY")
    gemini = os.environ.get("GEMINI_API_KEY")
    provider = _env("COPILOT_CHAT_PROVIDER").strip().lower() or "nim"
    if provider not in {"nim", "google"}:
        notes.append(f"COPILOT_CHAT_PROVIDER={provider!r} is unknown; using nim.")
        provider = "nim"
    if nv and not is_real_key(nv):
        notes.append("NVIDIA_API_KEY holds the placeholder value; NIM counts as missing.")
    laya_mode = _env("LAYA_MODE").strip().lower() or "local"
    if laya_mode not in {"local", "http", "off"}:
        notes.append(f"LAYA_MODE={laya_mode!r} is unknown; using local.")
        laya_mode = "local"
    return Settings(
        env_file=env_file,
        nvidia_api_key=nv if is_real_key(nv) else None,
        # Nemotron models (small, embeddings, reranker) may use a separate key.
        nemotron_api_key=nemo if is_real_key(nemo) else (nv if is_real_key(nv) else None),
        gemini_api_key=gemini if is_real_key(gemini) else None,
        chat_provider=provider,
        google_base_url=_env("GOOGLE_BASE_URL").rstrip("/"),
        google_chat_model=_env("GOOGLE_CHAT_MODEL"),
        google_small_model=_env("GOOGLE_SMALL_MODEL"),
        google_timeout=float(_env("GOOGLE_TIMEOUT")),
        laya_api_key=laya_key if is_real_key(laya_key) else None,
        nvidia_base_url=_env("NVIDIA_BASE_URL"),
        chat_model=_env("NIM_CHAT_MODEL"),
        small_model=_env("NIM_SMALL_MODEL"),
        embed_model=_env("NIM_EMBED_MODEL"),
        rerank_model=_env("NIM_RERANK_MODEL"),
        temperature=float(prof.get("llm.temperature", float(_env("NIM_TEMPERATURE")))),
        max_tokens=int(_env("NIM_MAX_TOKENS")),
        nim_timeout=float(_env("NIM_TIMEOUT")),
        laya_mode=laya_mode,
        laya_model=_env("LAYA_MODEL").strip() or "auto",
        laya_device=_env("LAYA_DEVICE").strip(),
        laya_base_url=_env("LAYA_BASE_URL").rstrip("/"),
        laya_timeout=float(_env("LAYA_TIMEOUT")),
        apis_live=_truthy(_env("COPILOT_APIS_LIVE")),
        http_contact=_env("COPILOT_HTTP_CONTACT"),
        live_tests=_truthy(_env("COPILOT_LIVE_TESTS")),
        profile=prof,
        notes=notes,
    )


# -------------------------------------------------------------------------- clock

def today(profile: Profile | None = None) -> dt.date:
    """The campus date. Profiles pin it (`app.today`) so demos and tests stay repeatable."""
    pinned = os.environ.get("COPILOT_TODAY") or (profile.get("app.today") if profile else None)
    if pinned:
        return dt.date.fromisoformat(str(pinned))
    return dt.date.today()


def runs_dir() -> Path:
    path = Path(os.environ.get("COPILOT_RUNS_DIR") or RUNS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path
