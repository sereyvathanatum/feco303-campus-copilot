"""OpenAI-compatible chat client over plain HTTP, used for NVIDIA NIM and Google AI Studio.

Both providers accept the same `/chat/completions` body, so one client serves both:
the request stays visible, tests can pass a recording fake session, and a provider
swap changes only the base URL, key, and model ID.

* Thought text (`<thought>…</thought>`, `<think>…</think>`) is stripped from replies;
  its length is recorded for the thinking-cost experiment (E12).
* 429 and 5xx responses are retried with backoff. A timeout marks the provider
  unhealthy for a few minutes so later calls fall back at once instead of waiting again.
* Images travel as base64 `image_url` content parts.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

THOUGHT = re.compile(r"<(thought|think)>.*?</\1>", re.DOTALL | re.IGNORECASE)
OPEN_THOUGHT = re.compile(r"^.*?</(thought|think)>", re.DOTALL | re.IGNORECASE)
UNHEALTHY_SECONDS = 300

_health: dict[str, float] = {}
_health_lock = threading.Lock()


class LLMError(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    ms: float = 0.0
    stub: bool = False
    tool_calls: list[dict] = field(default_factory=list)
    thought_chars: int = 0
    notes: list[str] = field(default_factory=list)


def strip_thoughts(text: str) -> tuple[str, int]:
    """Remove thought blocks; also a dangling `…</thought>` prefix when the opening tag was cut off."""
    before = len(text)
    text = THOUGHT.sub("", text)
    if re.search(r"</(thought|think)>", text, re.IGNORECASE):
        text = OPEN_THOUGHT.sub("", text)
    text = text.strip()
    return text, before - len(text)


def image_part(path: str | Path) -> dict:
    path = Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def mark_unhealthy(provider: str) -> None:
    with _health_lock:
        _health[provider] = time.monotonic() + UNHEALTHY_SECONDS


def is_healthy(provider: str) -> bool:
    with _health_lock:
        return time.monotonic() >= _health.get(provider, 0.0)


def reset_health() -> None:
    with _health_lock:
        _health.clear()


class OpenAICompatClient:
    def __init__(self, provider: str, base_url: str, api_key: str, model: str, timeout: float = 60.0,
                 retries: int = 2, session=None, thinking: bool = False, min_tokens: int = 4096) -> None:
        import requests

        self.min_tokens = min_tokens
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.thinking = thinking

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def request_body(self, messages: list[dict], max_tokens: int, temperature: float, tools: list[dict] | None,
                     json_mode: bool) -> dict:
        messages = [dict(m) for m in messages]
        if self.thinking and self.provider == "nim" and messages and messages[0]["role"] == "system":
            from .prompts import THINKING_PREFIX

            messages[0]["content"] = THINKING_PREFIX + messages[0]["content"]
        if self.provider == "google":
            # Gemma 4 on AI Studio always thinks, and thought tokens count against max_tokens.
            max_tokens = max(max_tokens, self.min_tokens)
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                "stream": False}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode and not tools:
            body["response_format"] = {"type": "json_object"}
        return body

    def complete(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.0,
                 tools: list[dict] | None = None, json_mode: bool = False, **_: object) -> LLMReply:
        import requests

        if not is_healthy(self.name):
            raise LLMError(f"{self.name} marked unhealthy after a recent timeout")
        body = self.request_body(messages, max_tokens, temperature, tools, json_mode)
        last = ""
        for attempt in range(self.retries + 1):
            started = time.perf_counter()
            try:
                response = self.session.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout,
                                             headers={"Authorization": f"Bearer {self.api_key}",
                                                      "Accept": "application/json"})
            except requests.Timeout as exc:
                mark_unhealthy(self.name)
                raise LLMError(f"{self.provider} timed out after {self.timeout:.0f} s") from exc
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5 * 2 ** attempt)
                continue
            ms = (time.perf_counter() - started) * 1000
            if response.status_code == 400 and "response_format" in body:
                body.pop("response_format")  # provider without JSON mode: fall back to prompt-level JSON
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {response.status_code}: {response.text[:160]}"
                time.sleep(min(8.0, 1.0 * 2 ** attempt))
                continue
            if response.status_code != 200:
                raise LLMError(f"{self.provider} HTTP {response.status_code}: {response.text[:200]}")
            payload = response.json()
            if isinstance(payload, list):
                payload = payload[0]
            message = payload["choices"][0]["message"]
            text, thought = strip_thoughts(message.get("content") or "")
            usage = payload.get("usage") or {}
            calls = []
            for call in message.get("tool_calls") or []:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": fn.get("arguments")}
                calls.append({"id": call.get("id"), "tool": fn.get("name"), "args": args})
            if not text and not calls:
                raise LLMError(f"{self.name} returned no answer text"
                               + (" (thinking used the whole token budget)" if thought else ""))
            return LLMReply(text=text, model=payload.get("model", self.model), provider=self.provider,
                            tokens_in=int(usage.get("prompt_tokens", 0)),
                            tokens_out=int(usage.get("completion_tokens", 0)), ms=round(ms, 1),
                            tool_calls=calls, thought_chars=thought)
        raise LLMError(f"{self.provider} failed after retries: {last}")


def parse_json_object(text: str) -> dict | None:
    """Tolerant JSON extraction: strips code fences and returns the first balanced object."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    while start != -1:
        depth, in_string, escape = 0, False, False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:index + 1])
                        return value if isinstance(value, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
