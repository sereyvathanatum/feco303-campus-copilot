"""Record live API responses into data/api_fixtures/ (and, with --jev, decision-model responses).

Maintenance only; needs network access. Fixture files are keyed the same way the
tools look them up, so offline runs replay exactly what was recorded here.

    python scripts/record_fixtures.py            # public APIs
    python scripts/record_fixtures.py --jev      # also Jev turn decisions for demo turns and eval cases
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from campus_copilot import config  # noqa: E402
from campus_copilot.tools import public_apis  # noqa: E402
from campus_copilot.tools.http import FIXTURES, HttpClient, fixture_key  # noqa: E402

BOOK_QUERIES = ["retrieval augmented generation", "deep learning", "khmer language", "machine learning"]
CONCEPTS = ["attention", "transformer", "embedding", "rag", "overfitting", "large language model", "lora"]


def save(api: str, params: dict | None, url: str, response: dict, note: str = "") -> Path:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"{fixture_key(api, params)}.json"
    record = {"recorded_at": dt.datetime.now().isoformat(timespec="seconds"), "api": api, "url": url,
              "params": params or {}, "note": note, "response": response}
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"recorded {path.relative_to(ROOT)}")
    return path


def record_public_apis(settings) -> None:
    http = HttpClient(settings, live=True)
    campus = settings.profile.get("campus", {})
    params = {"latitude": campus["latitude"], "longitude": campus["longitude"],
              "hourly": "precipitation_probability,precipitation,temperature_2m", "timezone": campus["timezone"],
              "forecast_days": 7}
    url = "https://api.open-meteo.com/v1/forecast"
    save("open_meteo", {}, url, http.get_json("open_meteo", url, params).data, "re-dated to the campus date on replay")
    url = "https://open.er-api.com/v6/latest/USD"
    save("er_api", {}, url, http.get_json("er_api", url).data)
    url = "https://openlibrary.org/search.json"
    for query in BOOK_QUERIES:
        data = http.get_json("openlibrary", url, {"q": query, "limit": 5,
                                                  "fields": "title,author_name,first_publish_year,isbn"}).data
        save("openlibrary", {"q": query}, url, data)
        time.sleep(1.1)  # Open Library asks for at most one anonymous request per second
    save("openlibrary", {}, url, json.loads((FIXTURES / f"{fixture_key('openlibrary', {'q': BOOK_QUERIES[1]})}.json")
                                            .read_text(encoding="utf-8"))["response"], "default search result")
    for concept in CONCEPTS:
        slug = public_apis.concept_title(concept).replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
        save("wikipedia", {"title": slug}, url, http.get_json("wikipedia", url).data)


def record_jev(settings) -> None:
    from campus_copilot.decisions import questions as qcat
    from campus_copilot.decisions.jev import JevDecider
    from campus_copilot.db import connection, queries

    conn = connection.read_connection()
    catalogue = qcat.turn_catalogue(queries.course_codes(conn))
    decider = JevDecider(settings, replay="record")
    spec = qcat.wire(catalogue)
    cases = []
    for path in (ROOT / "data" / "demo_turns.jsonl", ROOT / "eval" / "cases.jsonl"):
        if path.is_file():
            cases += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for case in cases:
        account = case.get("account_id", "A0001")
        history = [{"role": h["role"], "text": h["text"]} for h in case.get("history", [])]
        state = qcat.turn_state(case["message"], history, account, queries.enrolled_courses(conn, account),
                                case.get("image_text"))
        decision = decider.decide(state, spec)
        print(f"jev {'ok ' if decision.ok else 'ERR'} {decision.ms:5.0f} ms  {case['message'][:60]}")


def main() -> int:
    settings = config.get_settings("baseline")
    record_public_apis(settings)
    if "--jev" in sys.argv:
        if not settings.has_jev:
            print("TYPESAFE_API_KEY missing: Jev responses not recorded")
            return 1
        record_jev(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
