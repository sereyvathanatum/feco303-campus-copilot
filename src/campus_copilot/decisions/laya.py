"""Client for Laya, ConvAI's open-weights System One decision model (docs/laya_primer.md).

Two ways to reach the same model, chosen by `LAYA_MODE`:

* `local` (default): the `laya` Python package runs in this process (`pip install laya`). Its
  `Router` picks a checkpoint per request: `english` for English text, `multilingual` for Khmer
  and other languages. Weights download from Hugging Face on first use; no API key.
* `http`: a `laya-serve` process (`pip install "laya[serve]"`, then `laya-serve`) answers
  `POST {LAYA_BASE_URL}/systemone` with the same body and answer shape.

Common to both:

* Body: exactly `{"state", "model", "questions"}`; the answers come back as `choice`, `score`, `noul`.
* Model: profile `laya.model`, then `LAYA_MODEL`, then `auto` (the Router picks by language).
* Failures come back as data: `Decision(ok=False, status, error)`.
* Every call records the checkpoint that answered, the Router's reason, usage, latency, and the
  full `answers` object.
* Replay mode reads recorded responses keyed on a hash of the request body; record mode writes
  them (`scripts/record_fixtures.py --laya`), so tests and offline runs repeat a live run exactly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from ..config import DATA_DIR
from .base import Decision, DeciderMixin

log = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF = (0.5, 1.0, 2.0)
REPLAY_DIR = DATA_DIR / "fixtures" / "laya"
CHECKPOINTS = ("english", "multilingual", "typed-decisions")

_ROUTER = None
_ROUTER_LOCK = threading.Lock()


def body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def local_router(settings):
    """One `laya.Router` per process: checkpoints are large, so every decider shares it."""
    global _ROUTER
    with _ROUTER_LOCK:
        if _ROUTER is None:
            from laya import Router

            started = time.perf_counter()
            _ROUTER = Router(device=settings.laya_device or None, max_loaded=2)
            log.info("laya router ready in %.0f ms (device %s)", (time.perf_counter() - started) * 1000,
                     settings.laya_device or "auto")
        return _ROUTER


def _apply_budget(agent, profile) -> None:
    """Raise the token budgets once per checkpoint: long option lists otherwise lose their text.

    Laya encodes each question as `[CLS] instructions [SEP] options [SEP] state`. The instructions and
    options share `head_max_len` tokens (192 on the English checkpoint); an 11-option route question
    overruns that and every option is cut to a few tokens. `laya.head_max_len` and `laya.max_len`
    in the profile set both budgets; 0 keeps the checkpoint's own value.
    """
    if getattr(agent, "_copilot_budget", False):
        return
    head, total = int(profile.get("laya.head_max_len", 0) or 0), int(profile.get("laya.max_len", 0) or 0)
    if total:
        agent.cfg["max_len"] = max(total, int(agent.cfg.get("max_len", 512)))
    if head:
        agent.cfg["head_max_len"] = min(head, int(agent.cfg["max_len"]) - 64)
    agent._copilot_budget = True


class LayaDecider(DeciderMixin):
    name = "laya"
    stub = False

    def __init__(self, settings, session=None, replay: str | None = None, router=None) -> None:
        self.settings = settings
        self.mode = settings.laya_mode if settings.laya_mode in ("local", "http") else "local"
        self.model = settings.decision_model or "auto"
        self.base_url = settings.laya_base_url
        self.api_key = settings.laya_api_key or ""
        self.timeout = settings.laya_timeout
        self._session = session
        self._router = router
        # A local model shares one GPU or CPU: passages are batched into one forward pass instead of threads.
        self.workers = int(settings.profile.get("laya.passage_workers", 8)) if self.mode == "http" else 1
        # "replay" reads recorded responses, "record" also calls live and saves them, None calls live only.
        self.replay = replay or os.environ.get("COPILOT_LAYA_REPLAY") or None
        self.calls: list[dict] = []

    # ------------------------------------------------------------------ requests
    def request_body(self, state, questions: dict) -> dict:
        return {"state": state, "model": self.model, "questions": questions}

    @property
    def router(self):
        if self._router is None:
            self._router = local_router(self.settings)
        return self._router

    @property
    def session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def decide(self, state, questions: dict) -> Decision:
        body = self.request_body(state, questions)
        key = body_hash(body)
        if self.replay == "replay":
            path = REPLAY_DIR / f"{key}.json"
            if not path.is_file():
                return Decision(False, {}, self.name, self.model, error=f"no recorded response {path.name}")
            return self._decision(json.loads(path.read_text(encoding="utf-8")), 200, 0.0, replayed=True)
        started = time.perf_counter()
        if self.mode == "http":
            payload, status, error = self._post(body)
        else:
            payload, status, error = self._local(state, questions)
        ms = (time.perf_counter() - started) * 1000
        if payload is None:
            return Decision(False, {}, self.name, self.model, status=status, error=error or "request failed", ms=ms)
        if self.replay == "record":
            REPLAY_DIR.mkdir(parents=True, exist_ok=True)
            (REPLAY_DIR / f"{key}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                                                    encoding="utf-8")
        return self._decision(payload, 200, ms)

    def _local(self, state, questions: dict) -> tuple[dict | None, int | None, str | None]:
        try:
            router = self.router
            route = router.route(state, questions, model=None if self.model == "auto" else self.model)
            agent = router.load(route["model"])
            _apply_budget(agent, self.settings.profile)
            result = agent.system_one(state, questions)
        except Exception as exc:  # a missing package, a failed download, or a bad question: report, do not crash
            return None, None, f"{type(exc).__name__}: {exc}"
        return self._payload(result, dict(route)), 200, None

    def _post(self, body: dict) -> tuple[dict | None, int | None, str | None]:
        import requests

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last_status, last_error = None, ""
        for attempt in range(len(BACKOFF) + 1):
            try:
                response = self.session.post(f"{self.base_url}/systemone", json=body, timeout=self.timeout,
                                             headers=headers)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < len(BACKOFF):
                    time.sleep(BACKOFF[attempt])
                    continue
                break
            last_status = response.status_code
            if response.status_code == 200:
                payload = response.json()
                return self._payload(payload, payload.get("routing") or {}), 200, None
            last_error = response.text[:300]
            if response.status_code in RETRY_STATUS and attempt < len(BACKOFF):
                time.sleep(BACKOFF[attempt])
                continue
            break
        return None, last_status, last_error or "request failed"

    @staticmethod
    def _payload(result: dict, routing: dict) -> dict:
        """The stored shape: answers, usage, and which checkpoint answered and why."""
        checkpoint = routing.get("model")
        return {"model": f"laya/{checkpoint}" if checkpoint else result.get("model", "laya"),
                "answers": result.get("answers", {}), "usage": result.get("usage", {}),
                "routing": {k: routing.get(k) for k in ("model", "repo", "reason") if routing.get(k)}}

    def _decision(self, payload: dict, status: int, ms: float, replayed: bool = False) -> Decision:
        notes = ["replayed"] if replayed else []
        reason = (payload.get("routing") or {}).get("reason")
        if reason:
            notes.append(f"laya router: {reason}")
        decision = Decision(True, payload.get("answers", {}), self.name, payload.get("model", self.model),
                            usage=payload.get("usage", {}), ms=ms, status=status, notes=notes)
        self.calls.append({"model": decision.model, "usage": decision.usage, "ms": round(ms, 1),
                           "answers": decision.answers})
        return self.count(decision)

    # ------------------------------------------------- many states, same questions
    def decide_many(self, states: list, questions: dict) -> list[Decision]:
        """Local mode: states that route to the same checkpoint share one batched forward pass."""
        if self.mode != "local" or self.replay == "replay" or len(states) < 2:
            return super().decide_many(states, questions)
        out: list[Decision | None] = [None] * len(states)
        groups: dict[str, list[int]] = {}
        try:
            routes = [self.router.route(s, questions, model=None if self.model == "auto" else self.model)
                      for s in states]
        except Exception as exc:
            return [Decision(False, {}, self.name, self.model, error=f"{type(exc).__name__}: {exc}") for _ in states]
        for index, route in enumerate(routes):
            groups.setdefault(route["model"], []).append(index)
        for checkpoint, indexes in groups.items():
            started = time.perf_counter()
            try:
                agent = self.router.load(checkpoint)
                _apply_budget(agent, self.settings.profile)
                results = agent.predict_batch([states[i] for i in indexes], questions)
            except Exception as exc:
                for i in indexes:
                    out[i] = Decision(False, {}, self.name, self.model, error=f"{type(exc).__name__}: {exc}")
                continue
            ms = (time.perf_counter() - started) * 1000 / max(1, len(indexes))
            for i, result in zip(indexes, results):
                payload = self._payload(result, dict(routes[i]))
                if self.replay == "record":
                    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
                    path = REPLAY_DIR / f"{body_hash(self.request_body(states[i], questions))}.json"
                    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
                out[i] = self._decision(payload, 200, ms)
        return [d for d in out if d is not None]


def smoke_request() -> dict:
    """The reference call body (docs/laya_primer.md), stored as data/fixtures/laya_smoke_request.json."""
    return json.loads((DATA_DIR / "fixtures" / "laya_smoke_request.json").read_text(encoding="utf-8"))


def smoke(settings, session=None) -> tuple[Decision, dict]:
    body = smoke_request()
    decider = LayaDecider(settings, session=session)
    decider.model = body.get("model", decider.model)
    started = time.perf_counter()
    decision = decider.decide(body["state"], body["questions"])
    return decision, {"ms": round((time.perf_counter() - started) * 1000, 1), "body": body}


def ensure_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
