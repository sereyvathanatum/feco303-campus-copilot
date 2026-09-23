"""Thin HTTP client for TypeSafe Jev: `POST {TYPESAFE_BASE_URL}/systemone` (docs/implementation-plan.md §8.3).

* Body: exactly `{"state", "model", "questions"}` with a Bearer header.
* Model: profile `jev.model`, then `TYPESAFE_MODEL`, then `jev-latest`.
* Retries on 429, 529, and 5xx with backoff 0.5 s, 1 s, 2 s; no retry on 401 or 422.
* Failures come back as data: `Decision(ok=False, status, error)`.
* Every call records `model`, usage, latency, and the full `answers` object.
* Replay mode reads recorded responses keyed on a hash of the request body; record
  mode writes them (`scripts/record_fixtures.py`).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from ..config import DATA_DIR
from .base import Decision, DeciderMixin

RETRY_STATUS = {429, 529, 500, 502, 503, 504}
BACKOFF = (0.5, 1.0, 2.0)
REPLAY_DIR = DATA_DIR / "fixtures" / "jev"


def body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


class JevDecider(DeciderMixin):
    name = "jev"
    stub = False

    def __init__(self, settings, session=None, replay: str | None = None) -> None:
        import requests

        self.api_key = settings.typesafe_api_key or ""
        self.base_url = settings.typesafe_base_url
        self.model = settings.jev_model or "jev-latest"
        self.timeout = settings.typesafe_timeout
        self.session = session or requests.Session()
        self.workers = int(settings.profile.get("jev.passage_workers", 8))
        # "replay" reads recorded responses, "record" also calls live and saves them, None calls live only.
        self.replay = replay or os.environ.get("COPILOT_JEV_REPLAY") or None
        self.calls: list[dict] = []

    def request_body(self, state, questions: dict) -> dict:
        return {"state": state, "model": self.model, "questions": questions}

    def decide(self, state, questions: dict) -> Decision:
        body = self.request_body(state, questions)
        key = body_hash(body)
        if self.replay == "replay":
            path = REPLAY_DIR / f"{key}.json"
            if not path.is_file():
                return Decision(False, {}, self.name, self.model, error=f"no recorded response {path.name}")
            return self._decision(json.loads(path.read_text(encoding="utf-8")), 200, 0.0, replayed=True)
        import requests

        last_status, last_error = None, ""
        for attempt in range(len(BACKOFF) + 1):
            started = time.perf_counter()
            try:
                response = self.session.post(f"{self.base_url}/systemone", json=body, timeout=self.timeout,
                                             headers={"Authorization": f"Bearer {self.api_key}",
                                                      "Content-Type": "application/json"})
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < len(BACKOFF):
                    time.sleep(BACKOFF[attempt])
                    continue
                break
            ms = (time.perf_counter() - started) * 1000
            last_status = response.status_code
            if response.status_code == 200:
                payload = response.json()
                if self.replay == "record":
                    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
                    (REPLAY_DIR / f"{key}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                                                            encoding="utf-8")
                return self._decision(payload, 200, ms)
            last_error = response.text[:300]
            if response.status_code in RETRY_STATUS and attempt < len(BACKOFF):
                time.sleep(BACKOFF[attempt])
                continue
            break
        return Decision(False, {}, self.name, self.model, status=last_status, error=last_error or "request failed")

    def _decision(self, payload: dict, status: int, ms: float, replayed: bool = False) -> Decision:
        decision = Decision(True, payload.get("answers", {}), self.name, payload.get("model", self.model),
                            usage=payload.get("usage", {}), ms=ms, status=status,
                            notes=["replayed"] if replayed else [])
        self.calls.append({"model": decision.model, "usage": decision.usage, "ms": round(ms, 1),
                           "answers": decision.answers})
        return self.count(decision)


def smoke_request() -> dict:
    """The reference call body (docs/jev_primer.md), stored as data/fixtures/jev_smoke_request.json."""
    return json.loads((DATA_DIR / "fixtures" / "jev_smoke_request.json").read_text(encoding="utf-8"))


def smoke(settings, session=None) -> tuple[Decision, dict]:
    body = smoke_request()
    decider = JevDecider(settings, session=session)
    decider.model = body.get("model", decider.model)
    started = time.perf_counter()
    decision = decider.decide(body["state"], body["questions"])
    return decision, {"ms": round((time.perf_counter() - started) * 1000, 1), "body": body}


def ensure_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
