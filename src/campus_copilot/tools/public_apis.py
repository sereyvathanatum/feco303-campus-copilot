"""Public-API tools (docs/implementation-plan.md §6.3). No keys; every result carries attribution and `fetched_at`.

* `campus_weather`: Open-Meteo forecast (CC BY 4.0 attribution shown in answers).
* `convert_currency`: ExchangeRate-API open endpoint (`open.er-api.com/v6/latest/USD`).
* `search_books`: Open Library search (1 request per second anonymously; cached).
* `concept_summary`: Wikipedia REST page summary. The text is untrusted and is wrapped
  as `<tool_result>` data before any model sees it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .dates import normalize_time, resolve_date
from .http import ApiError
from .registry import ToolContext, ToolSpec

FIXED_RATE = 4100.0  # a fixed teaching rate for comparison with the live rate
ATTRIBUTION = {
    "open_meteo": "Weather data by Open-Meteo.com (CC BY 4.0)",
    "er_api": "Rates by Exchange Rate API (open.er-api.com)",
    "openlibrary": "Book data from Open Library (openlibrary.org)",
    "wikipedia": "Summary from Wikipedia (CC BY-SA 4.0)",
}
CONCEPT_TITLES = {
    "attention": "Attention (machine learning)", "self-attention": "Attention (machine learning)",
    "transformer": "Transformer (deep learning)", "transformers": "Transformer (deep learning)",
    "embedding": "Word embedding", "embeddings": "Word embedding", "rag": "Retrieval-augmented generation",
    "retrieval-augmented generation": "Retrieval-augmented generation", "llm": "Large language model",
    "large language model": "Large language model", "fine-tuning": "Fine-tuning (deep learning)",
    "lora": "Fine-tuning (deep learning)", "overfitting": "Overfitting", "gradient descent": "Gradient descent",
    "backpropagation": "Backpropagation", "tokenization": "Lexical analysis", "prompt injection": "Prompt injection",
}


class WeatherArgs(BaseModel):
    date: str = Field("today", description="today, tomorrow, a weekday name, or YYYY-MM-DD.")
    hour: str | None = Field(None, description="Hour of interest, HH:MM or '2 pm'; omit for the whole day.")
    until: str | None = Field(None, description="End of a time window, HH:MM; used with hour.")


class CurrencyArgs(BaseModel):
    amount: float = Field(gt=0, description="Amount of money to convert.")
    direction: str = Field(description="usd_to_khr or khr_to_usd.", pattern="^(usd_to_khr|khr_to_usd)$")


class BookSearchArgs(BaseModel):
    query: str = Field(min_length=2, description="Title, author, or subject words.")


class ConceptArgs(BaseModel):
    topic: str = Field(min_length=2, description="The concept or term to summarise, for example 'attention'.")


def _meta(api: str, response) -> dict:
    return {"attribution": ATTRIBUTION[api], "fetched_at": response.fetched_at, "source": response.source}


def campus_weather(ctx: ToolContext, args: WeatherArgs) -> dict:
    day = resolve_date(args.date, ctx.today)
    campus = ctx.settings.profile.get("campus", {})
    params = {"latitude": campus.get("latitude", 11.5564), "longitude": campus.get("longitude", 104.9282),
              "hourly": "precipitation_probability,precipitation,temperature_2m",
              "timezone": campus.get("timezone", "Asia/Phnom_Penh"), "forecast_days": 7}
    try:
        response = ctx.http.get_json("open_meteo", "https://api.open-meteo.com/v1/forecast", params, fixture_params={})
    except ApiError as exc:
        return {"ok": False, "error": str(exc), "summary": f"Weather lookup failed: {exc}."}
    hourly = response.data.get("hourly", {})
    rows = [{"time": t, "rain_probability": p, "precipitation_mm": mm, "temperature_c": temp}
            for t, p, mm, temp in zip(hourly.get("time", []), hourly.get("precipitation_probability", []),
                                      hourly.get("precipitation", []), hourly.get("temperature_2m", []))
            if t.startswith(day.isoformat())]
    if not rows:
        return {"ok": False, "error": f"no forecast for {day.isoformat()} (forecasts cover 7 days)",
                "summary": f"No forecast is available for {day.isoformat()}.", **_meta("open_meteo", response)}
    window = rows
    label = day.isoformat()
    if args.hour:
        start = normalize_time(args.hour, default_pm=True)
        end = normalize_time(args.until, default_pm=True) if args.until else start
        window = [r for r in rows if start[:2] <= r["time"][11:13] <= end[:2]] or rows
        label += f" {start}" + (f"–{end}" if end != start else "")
    top = max(window, key=lambda r: r["rain_probability"] or 0)
    temps = [r["temperature_c"] for r in window if r["temperature_c"] is not None]
    summary = (f"Forecast for campus, {label}: rain probability up to {top['rain_probability']}% "
               f"(around {top['time'][11:16]}), {min(temps):.0f}–{max(temps):.0f} °C.")
    return {"data": {"date": day.isoformat(), "hours": window}, "summary": summary, **_meta("open_meteo", response)}


def convert_currency(ctx: ToolContext, args: CurrencyArgs) -> dict:
    try:
        response = ctx.http.get_json("er_api", "https://open.er-api.com/v6/latest/USD", None, fixture_params={})
    except ApiError as exc:
        return {"ok": False, "error": str(exc), "summary": f"Exchange-rate lookup failed: {exc}."}
    rate = float(response.data.get("rates", {}).get("KHR", 0) or 0)
    if rate <= 0:
        return {"ok": False, "error": "no KHR rate in the response", "summary": "No KHR rate available.",
                **_meta("er_api", response)}
    if args.direction == "usd_to_khr":
        result, fixed = args.amount * rate, args.amount * FIXED_RATE
        summary = f"{args.amount:,.2f} USD = {result:,.0f} KHR at {rate:,.2f} KHR per USD"
    else:
        result, fixed = args.amount / rate, args.amount / FIXED_RATE
        summary = f"{args.amount:,.0f} KHR = {result:,.2f} USD at {rate:,.2f} KHR per USD"
    updated = response.data.get("time_last_update_utc", "")
    summary += f" (rate updated {updated})." if updated else "."
    return {"data": {"amount": args.amount, "direction": args.direction, "rate": rate, "result": round(result, 2),
                     "fixed_rate": FIXED_RATE, "result_at_fixed_rate": round(fixed, 2)},
            "summary": summary, **_meta("er_api", response)}


def search_books(ctx: ToolContext, args: BookSearchArgs) -> dict:
    params = {"q": args.query, "limit": 5, "fields": "title,author_name,first_publish_year,isbn"}
    try:
        response = ctx.http.get_json("openlibrary", "https://openlibrary.org/search.json", params,
                                     fixture_params={"q": args.query})
    except ApiError as exc:
        return {"ok": False, "error": str(exc), "summary": f"Open Library search failed: {exc}."}
    docs = response.data.get("docs", [])[:5]
    rows = [{"title": d.get("title"), "authors": ", ".join(d.get("author_name", [])[:3]),
             "year": d.get("first_publish_year"), "isbn": (d.get("isbn") or [None])[0]} for d in docs]
    if not rows:
        return {"data": [], "summary": f"Open Library has no match for '{args.query}'.", **_meta("openlibrary", response)}
    parts = [f"'{r['title']}' by {r['authors'] or 'unknown'} ({r['year'] or 'n.d.'})" for r in rows[:3]]
    return {"data": rows, "summary": "Outside the campus library, Open Library lists: " + "; ".join(parts) + ".",
            **_meta("openlibrary", response)}


def concept_title(topic: str) -> str:
    key = topic.strip().strip("'\"").lower()
    return CONCEPT_TITLES.get(key, topic.strip().strip("'\"").capitalize())


def concept_summary(ctx: ToolContext, args: ConceptArgs) -> dict:
    title = concept_title(args.topic)
    slug = title.replace(" ", "_")
    try:
        response = ctx.http.get_json("wikipedia", f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}", None,
                                     fixture_params={"title": slug})
    except ApiError as exc:
        return {"ok": False, "error": str(exc), "summary": f"Wikipedia lookup failed: {exc}."}
    extract = re.sub(r"\s+", " ", response.data.get("extract", "")).strip()
    if not extract:
        return {"ok": False, "error": "empty summary", "summary": f"Wikipedia has no summary for '{title}'.",
                **_meta("wikipedia", response)}
    return {"data": {"title": response.data.get("title", title), "extract": extract,
                     "url": (response.data.get("content_urls", {}).get("desktop", {}) or {}).get("page")},
            "summary": f"External source (Wikipedia, '{response.data.get('title', title)}'): {extract[:600]}",
            "untrusted": True, **_meta("wikipedia", response)}


SPECS = [
    ToolSpec("campus_weather", "Campus weather forecast for a day or a time window (Open-Meteo).", WeatherArgs,
             campus_weather, kind="api", source="Open-Meteo"),
    ToolSpec("convert_currency", "Convert between US dollars and Cambodian riel at the latest rate.", CurrencyArgs,
             convert_currency, kind="api", source="ExchangeRate-API open access"),
    ToolSpec("search_books", "Search books outside the campus library (Open Library).", BookSearchArgs, search_books,
             kind="api", source="Open Library"),
    ToolSpec("concept_summary", "Short external summary of a general concept (Wikipedia); untrusted text.",
             ConceptArgs, concept_summary, kind="api", source="Wikipedia REST"),
]
