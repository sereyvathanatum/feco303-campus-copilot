"""One HTTP layer for the public-API tools (docs/implementation-plan.md §8.6).

* 10 s timeout, 2 retries, `User-Agent: FECO303-CampusCopilot/1.0 (+contact)`.
* `requests-cache` with a TTL per API, stored in `runs/http_cache.sqlite`.
* Fixture replay from `data/api_fixtures/` when live APIs are off (`apis.live = false`,
  `COPILOT_APIS_LIVE=false`, or offline mode). Weather fixtures are re-dated so that
  their first day is the campus "today".
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config

FIXTURES = config.DATA_DIR / "api_fixtures"
TTL = {"open_meteo": 3600, "er_api": 12 * 3600, "openlibrary": 24 * 3600, "wikipedia": 24 * 3600, "nager": 7 * 86400}
TIMEOUT = 10.0
RETRIES = 2


class ApiError(RuntimeError):
    pass


@dataclass
class ApiResponse:
    data: dict
    source: str            # live | cache | fixture | fixture (re-dated)
    fetched_at: str
    ms: float
    url: str


def fixture_key(api: str, params: dict | None) -> str:
    if not params:
        return f"{api}__default"
    text = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
    return f"{api}__{slug}"


def fixture_path(api: str, params: dict | None) -> Path:
    return FIXTURES / f"{fixture_key(api, params)}.json"


class HttpClient:
    def __init__(self, settings, live: bool | None = None, session=None, fixtures_dir: Path | None = None) -> None:
        self.settings = settings
        self.live = settings.use_live_apis if live is None else live
        self.contact = settings.http_contact
        self.fixtures_dir = fixtures_dir or FIXTURES
        self._session = session
        self.today = config.today(settings.profile)

    @property
    def user_agent(self) -> str:
        return f"FECO303-CampusCopilot/1.0 (+{self.contact})"

    def session(self):
        if self._session is None:
            try:
                import requests_cache

                self._session = requests_cache.CachedSession(
                    str(config.runs_dir() / "http_cache"), backend="sqlite", expire_after=3600,
                    allowable_codes=(200,), stale_if_error=False)
            except ImportError:  # pragma: no cover
                import requests

                self._session = requests.Session()
        return self._session

    def get_json(self, api: str, url: str, params: dict | None = None, fixture_params: dict | None = None) -> ApiResponse:
        if not self.live:
            return self._fixture(api, fixture_params if fixture_params is not None else params, url)
        import requests

        last = ""
        for attempt in range(RETRIES + 1):
            started = time.perf_counter()
            try:
                kwargs = {"params": params, "timeout": TIMEOUT, "headers": {"User-Agent": self.user_agent,
                                                                          "Accept": "application/json"}}
                if hasattr(self.session(), "cache"):
                    kwargs["expire_after"] = TTL.get(api, 3600)
                response = self.session().get(url, **kwargs)
            except requests.Timeout as exc:
                last = f"timeout after {TIMEOUT:.0f} s"
                if attempt < RETRIES:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
                raise ApiError(last) from exc
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < RETRIES:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
                raise ApiError(last) from exc
            ms = (time.perf_counter() - started) * 1000
            if response.status_code == 200:
                cached = bool(getattr(response, "from_cache", False))
                return ApiResponse(response.json(), "cache" if cached else "live",
                                   dt.datetime.now().isoformat(timespec="seconds"), round(ms, 1), url)
            last = f"HTTP {response.status_code}"
            if response.status_code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise ApiError(last)
        raise ApiError(last or "request failed")

    def _fixture(self, api: str, params: dict | None, url: str) -> ApiResponse:
        folder = self.fixtures_dir
        variant = self.settings.profile.get("apis.fixture_variant", "")  # "poisoned" in E13
        candidates = [f"{fixture_key(api, params)}__{variant}" if variant else None, fixture_key(api, params),
                      f"{api}__default__{variant}" if variant else None, f"{api}__default"]
        path = next((folder / f"{c}.json" for c in candidates if c and (folder / f"{c}.json").is_file()),
                    folder / f"{api}__default.json")
        if not path.is_file():
            raise ApiError(f"no recorded fixture for {api} {params or ''} (live APIs are off)")
        record = json.loads(path.read_text(encoding="utf-8"))
        data = record.get("response", record)
        source = "fixture"
        if api == "open_meteo":
            data, shifted = redate_forecast(data, self.today)
            source = "fixture (re-dated)" if shifted else source
        return ApiResponse(data, source, record.get("recorded_at", ""), 0.0, url)


def redate_forecast(data: dict, today: dt.date) -> tuple[dict, bool]:
    """Shift an Open-Meteo hourly forecast so its first day is `today` (fixture replay only)."""
    times = (data.get("hourly") or {}).get("time") or []
    if not times:
        return data, False
    first = dt.date.fromisoformat(times[0][:10])
    delta = today - first
    if delta.days == 0:
        return data, False
    data = json.loads(json.dumps(data))
    data["hourly"]["time"] = [(dt.datetime.fromisoformat(t) + delta).strftime("%Y-%m-%dT%H:%M") for t in times]
    return data, True


def body_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]
