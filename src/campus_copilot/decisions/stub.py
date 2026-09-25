"""Rule-based stub decider, labelled `STUB` (docs/implementation-plan.md §8.3).

A keyword router plus simple regexes over English, romanized Khmer, and Khmer
script. It answers the same questions in the same wire shape as Laya, so the graph
cannot tell them apart. A matched option gets probability 0.9 and the rest share
what is left; with no match the spread is flat. It doubles as the "rule" baseline
in E05, including its known weaknesses (paraphrases, keyword false positives).
"""

from __future__ import annotations

import re

from ..textutil import coverage
from .base import Decision, DeciderMixin
from .questions import DATA_ROUTES, ROUTE_CRITERIA, WEEKDAYS

F = re.IGNORECASE

ROUTE_PATTERNS: dict[str, list[str]] = {
    "timetable": [r"\btimetable\b", r"\bschedule\b", r"\b(class|classes|lectures?)\b", r"\bwhen and where\b",
                  r"\blab\b.*\b(this week|today|tomorrow|next week)\b", r"\bmoung rien\b", r"\bkalvipheak\b",
                  "កាលវិភាគ", "ម៉ោងសិក្សា"],
    "deadlines": [r"\bdeadlines?\b", r"\bdue\b", r"\bsubmit\b.*\bby\b", r"\bwhat.*assignments?.*(this|next) week\b",
                  "ថ្ងៃផុតកំណត់"],
    "calendar": [r"\bcalendar\b", r"\bholidays?\b", r"\bseminars?\b", r"\bexam week\b", r"\bevents?\b",
                 "ប្រតិទិន", "ថ្ងៃឈប់សម្រាក"],
    "rooms": [r"\brooms?\b", r"\bprojector\b", r"\b(book|reserve) (it|that|this|one|the room|a room)\b",
              r"^\s*(please\s+)?(book|reserve)\b", "បន្ទប់"],
    "library": [r"\bisbn\b", r"\b97[89]\d{10}\b", r"\bon the shelf\b", r"\bbooks?\b(?! (it|a room|the room|that|this))",
                r"\bloans?\b", r"\bholds?\b", r"\bborrow", "សៀវភៅ"],
    "weather": [r"\bweather\b", r"\brain(ing|y)?\b", r"\bforecast\b", r"\btemperature\b", r"\bhot\b", r"\bplieng\b",
                "អាកាសធាតុ", "ភ្លៀង"],
    "currency": [r"\bconvert\b", r"\bexchange\b", r"\busd\b", r"\bdollars?\b", r"\bdolla\b", r"\briels?\b", r"\bkhr\b",
                 r"\bluy\b", r"\$\s?\d", r"\bchange \d", "ដុល្លារ", "រៀល",
                 "ប្តូរ"],
    "concept": [r"\bwhat does .+ mean\b", r"\bmeaning of\b", r"\bexplain\b", r"\bdefine\b", r"\bdefinition\b",
                r"\bin transformers\b", r"\bwhat (is|are) (an? )?(transformer|attention|embeddings?|neural network|"
                r"gradient descent|backpropagation|overfitting|tokeni[sz]ation)"],
    "chit_chat": [r"^\s*(hi|hello|hey|thanks|thank\s+\w+|good (morning|afternoon|evening)|how are)\b",
                  "សួស្តី", r"\bsusadei\b", "អរគុណ"],
    "handbook": [r"\b(rules?|policy|policies|penalty|penalties|handbook|attendance|missed|absences?|late|exams?|grades?|"
                 r"grading|fines?|plagiarism|extensions?|wi-?fi|password|id card|fees?|tuition|opening hours|open|"
                 r"printing|counsell?ing|cafeteria|parking|menu|integrity|ai tools?|midterm|final exam)\b",
                 "វត្តមាន", "ពិន្ទុ",
                 "ប្រឡង", "ថ្លៃសិក្សា"],
}
COMPILED = {route: [re.compile(p, F) for p in pats] for route, pats in ROUTE_PATTERNS.items()}

WANTS_CHANGE = [re.compile(p, F) for p in (
    r"^\s*(please\s+)?(book|reserve)\b", r"\b(book|reserve) (it|that|this|a|the|one|room)\b", r"\bplace a hold\b",
    r"\bhold (it|this|that)\b", r"\bcancel\b", r"\badd (this|it|that)\b.*\b(calendar|schedule)\b", r"\bregister\b",
    "កក់")]
WANTS_STAFF = re.compile(r"charged twice|double charge|refund|nobody answers|no one answers|(speak|talk) to (a |someone|staff)"
                         r"|complain|\bhuman\b|staff member|wrong charge", F)
INJECTION = re.compile(r"ignore (all |any )?(the )?(previous|prior|above|earlier)? ?(rules|instructions)|system prompt|"
                       r"hidden instructions|reveal (the |its |all )?(rules|instructions|prompt)|disregard (the |all )?"
                       r"(rules|instructions)|yo[u] are now|developer mode|jailbreak|print (the |its )?instructions", F)
PASSAGE_INJECTION = re.compile(r"ignore (all |any )?(previous|prior|earlier)? ?(rules|instructions)|assistants? (must|should) "
                               r"(now )?(ignore|reveal|say)|system prompt|disregard (the |all )?(rules|instructions)|"
                               r"new instructions for (the |any )?(ai|assistant)", F)
OTHER_ACCOUNT_WORDS = re.compile(r"another account|other account|someone else'?s|classmate'?s|friend'?s "
                                 r"(loans|bookings|records|timetable|grades)", F)
MISCONDUCT = re.compile(r"\bcheat|exam answers|leak(ed)? exam|fake (a )?(medical )?certificate|\bforge|bypass attendance|"
                        r"sign in for (a )?friend|attendance for (a )?friend|write (the|this) assignment for", F)
ACCOUNT_ID = re.compile(r"\bA\d{4}\b")
COURSE = re.compile(r"\b([A-Za-z]{4}\d{3})\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?|[០-៩]+")
FOLLOW_START = re.compile(r"^\s*(and|also|what about|how about|then)\b", F)
PRONOUN = re.compile(r"\b(it|that|them|those|then)\b", F)
QUESTION = re.compile(r"\?\s*$|^\s*(what|when|where|who|how|which|why|is|are|can|does|do)\b|តើ", F)
USD = re.compile(r"\busd\b|\bdollars?\b|\bdolla\b|\$|ដុល្លារ", F)
KHR = re.compile(r"\briels?\b|\bkhr\b|\bluy( khmer)?\b|រៀល", F)
TO_KHR = re.compile(r"\b(to|in|into)\s+(riels?|khr|luy)|ទៅជារៀល|how many (riels?|khr)", F)
TO_USD = re.compile(r"\b(to|in|into)\s+(usd|dollars?|dolla)|ទៅជាដុល្លារ|"
                    r"how many (usd|dollars?)", F)
SPECIFIC_TIME = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}(:\d{2})?\s*[-–]\s*\d{1,2}(:\d{2})?\s*(am|pm)?\b"
                           r"|\b\d{1,2}:\d{2}\b", F)
DAY_WORDS = {"today": [r"\btoday\b", r"\btngai nis\b", "ថ្ងៃនេះ"],
             "tomorrow": [r"\btomorrow\b", r"\bsa-?ek\b", "ថ្ងៃស្អែក"]}


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def choice_answer(options: list[str], weights: dict[str, float]) -> dict:
    """Probabilities: 0.9 shared by the weighted options, the rest spread over the others; flat when unweighted."""
    weights = {k: v for k, v in weights.items() if v > 0 and k in options}
    if not weights:
        probs = {o: round(1.0 / len(options), 4) for o in options}
    else:
        total = sum(weights.values())
        others = [o for o in options if o not in weights]
        rest = 0.1 / len(others) if others else 0.0
        head = 0.9 if others else 1.0
        probs = {o: round(head * weights[o] / total if o in weights else rest, 4) for o in options}
    best = max(probs, key=probs.get)
    return {"type": "choice", "choice": best, "confidence": probs[best], "probabilities": probs}


def noul_answer(value: float) -> dict:
    return {"type": "noul", "noul": round(max(0.0, min(1.0, value)), 4)}


def score_answer(levels: int, expected: float) -> dict:
    expected = max(0.0, min(levels - 1, expected))
    low = int(expected)
    high = min(levels - 1, low + 1)
    frac = expected - low
    probs = {str(i): 0.0 for i in range(levels)}
    probs[str(low)] += round(1 - frac, 4)
    probs[str(high)] += round(frac, 4)
    return {"type": "score", "score": round(expected, 4), "confidence": round(max(probs.values()), 4),
            "probabilities": probs}


class Context:
    def __init__(self, state) -> None:
        state = state if isinstance(state, dict) else {"message": str(state)}
        self.state = state
        self.message = str(state.get("message", ""))
        self.history = state.get("history") or []
        self.user_history = [h.get("text", "") for h in self.history if h.get("role") == "user"]
        self.session = state.get("session") or {}
        self.image_text = state.get("image_text") or ""
        self.text = f"{self.message}\n{self.image_text}".strip()

    @property
    def last_user(self) -> str:
        return self.user_history[-1] if self.user_history else ""

    def follow_up(self) -> bool:
        if not self.history:
            return False
        words = self.message.split()
        return bool(FOLLOW_START.search(self.message) or PRONOUN.search(self.message) or len(words) <= 3)

    def route_hits(self, text: str) -> dict[str, float]:
        hits = {route: float(sum(1 for p in pats if p.search(text))) for route, pats in COMPILED.items()}
        if any(hits[r] for r in DATA_ROUTES):
            hits["handbook"] *= 0.5  # generic rule words yield to a specific lookup
        return {r: h for r, h in hits.items() if h}


class StubDecider(DeciderMixin):
    name = "stub"
    stub = True

    def decide(self, state, questions: dict) -> Decision:
        ctx = Context(state)
        answers = {}
        for qid, spec in questions.items():
            handler = getattr(self, f"_q_{qid}", None)
            answers[qid] = handler(ctx, spec) if handler else self._default(spec)
        return Decision(True, answers, self.name, "stub-rules", stub=True, notes=["STUB"])

    # ------------------------------------------------------------- defaults
    @staticmethod
    def _default(spec: dict) -> dict:
        if spec["type"] == "noul":
            return noul_answer(0.5)
        if spec["type"] == "choice":
            return choice_answer(list(spec["criteria"]), {})
        return score_answer(len(spec["criteria"]), (len(spec["criteria"]) - 1) / 2)

    # ---------------------------------------------------------------- route
    def _routes(self, ctx: Context) -> dict[str, float]:
        hits = ctx.route_hits(ctx.text)
        if (not hits or set(hits) == {"handbook"}) and ctx.follow_up() and ctx.last_user:
            inherited = ctx.route_hits(ctx.last_user)
            if inherited and not (set(inherited) == {"handbook"} and hits):
                return inherited
        return hits

    def _q_route(self, ctx: Context, spec: dict) -> dict:
        options = list(spec.get("criteria", ROUTE_CRITERIA))
        hits = self._routes(ctx)
        if not hits and QUESTION.search(ctx.message):
            hits = {"handbook": 0.4}  # an unmatched campus question goes to the handbook, which can abstain
        if len(hits) > 1:
            best = max(hits.values())
            hits = {r: (h * 1.5 if h == best else h) for r, h in hits.items()}
        return choice_answer(options, hits)

    def _q_several_sources(self, ctx: Context, spec: dict) -> dict:
        data = [r for r in ctx.route_hits(ctx.message) if r in DATA_ROUTES - {"concept"}]
        return noul_answer(0.85 if len(data) >= 2 else 0.08)

    def _q_follow_up(self, ctx: Context, spec: dict) -> dict:
        return noul_answer(0.85 if ctx.follow_up() else 0.1)

    def _q_missing_info(self, ctx: Context, spec: dict) -> dict:
        hits = self._routes(ctx)
        if "rooms" in hits and not (SPECIFIC_TIME.search(ctx.text) or ctx.follow_up()):
            return noul_answer(0.7)
        if "currency" in hits and not NUMBER.search(ctx.text):
            return noul_answer(0.75)
        return noul_answer(0.2)

    def _q_wants_change(self, ctx: Context, spec: dict) -> dict:
        return noul_answer(0.9 if _any(WANTS_CHANGE, ctx.message) else 0.05)

    def _q_wants_staff(self, ctx: Context, spec: dict) -> dict:
        return noul_answer(0.88 if WANTS_STAFF.search(ctx.message) else 0.05)

    def _q_complexity(self, ctx: Context, spec: dict) -> dict:
        levels = len(spec["criteria"])
        if re.search(r"\b(explain|why|compare|difference|how does)\b", ctx.message, F):
            return score_answer(levels, 1.8)
        return score_answer(levels, 0.2 if len(ctx.message.split()) <= 6 else 1.0)

    # ---------------------------------------------------------------- guards
    def _q_injection(self, ctx: Context, spec: dict) -> dict:
        passage = ctx.state.get("passage")
        if passage is not None:  # passage question: instructions aimed at the assistant inside a document
            return noul_answer(0.92 if PASSAGE_INJECTION.search(passage) else 0.02)
        return noul_answer(0.95 if INJECTION.search(ctx.text) else 0.03)

    def _other_account(self, ctx: Context) -> float:
        own = ctx.session.get("account_id")
        ids = set(ACCOUNT_ID.findall(ctx.message))
        if ids and (own is None or any(i != own for i in ids)):
            return 0.95
        return 0.8 if OTHER_ACCOUNT_WORDS.search(ctx.message) else 0.03

    def _q_other_account(self, ctx: Context, spec: dict) -> dict:
        return noul_answer(self._other_account(ctx))

    def _q_misconduct(self, ctx: Context, spec: dict) -> dict:
        return noul_answer(0.9 if MISCONDUCT.search(ctx.message) else 0.02)

    def _q_guard_severity(self, ctx: Context, spec: dict) -> dict:
        top = max(0.95 if INJECTION.search(ctx.text) else 0.0, self._other_account(ctx),
                  0.9 if MISCONDUCT.search(ctx.message) else 0.0)
        level = 2.4 if top >= 0.9 else 2.0 if top >= 0.7 else 1.0 if top >= 0.35 else 0.05
        return score_answer(len(spec["criteria"]), level)

    # ------------------------------------------------------------- arguments
    def _q_course(self, ctx: Context, spec: dict) -> dict:
        options = list(spec["criteria"])
        for text in [ctx.message, *reversed(ctx.user_history)]:
            for code in COURSE.findall(text):
                if code.upper() in options:
                    return choice_answer(options, {code.upper(): 1.0})
        return choice_answer(options, {"not_stated": 1.0})

    def _q_day(self, ctx: Context, spec: dict) -> dict:
        options = list(spec["criteria"])
        sources = [ctx.message] + (list(reversed(ctx.user_history)) if ctx.follow_up() else [])
        for text in sources:
            for day, pats in DAY_WORDS.items():
                if any(re.search(p, text, F) for p in pats):
                    return choice_answer(options, {day: 1.0})
            for day in WEEKDAYS:
                if re.search(rf"\b{day}\b", text, F):
                    return choice_answer(options, {day: 1.0})
        return choice_answer(options, {"not_stated": 1.0})

    def _q_time_of_day(self, ctx: Context, spec: dict) -> dict:
        options = list(spec["criteria"])
        sources = [ctx.message] + (list(reversed(ctx.user_history)) if ctx.follow_up() else [])
        for text in sources:
            if SPECIFIC_TIME.search(text):
                return choice_answer(options, {"specific_time": 1.0})
            for word in ("morning", "afternoon", "evening"):
                if re.search(rf"\b{word}\b", text, F):
                    return choice_answer(options, {word: 1.0})
        return choice_answer(options, {"not_stated": 1.0})

    def _feature(self, ctx: Context, pattern: str, yes: float) -> dict:
        texts = [ctx.message] + ([ctx.last_user] if ctx.follow_up() else [])
        return noul_answer(yes if any(re.search(pattern, t, F) for t in texts) else 0.04)

    def _q_needs_projector(self, ctx: Context, spec: dict) -> dict:
        return self._feature(ctx, r"\bprojector\b", 0.95)

    def _q_needs_pcs(self, ctx: Context, spec: dict) -> dict:
        return self._feature(ctx, r"\b(pcs?|computers?)\b", 0.9)

    def _q_currency_direction(self, ctx: Context, spec: dict) -> dict:
        options = list(spec["criteria"])
        text = ctx.message
        if TO_KHR.search(text):
            return choice_answer(options, {"usd_to_khr": 1.0})
        if TO_USD.search(text):
            return choice_answer(options, {"khr_to_usd": 1.0})
        usd, khr = USD.search(text), KHR.search(text)
        if usd and khr:
            return choice_answer(options, {"usd_to_khr" if usd.start() < khr.start() else "khr_to_usd": 1.0})
        return choice_answer(options, {"not_stated": 1.0})

    def _q_amount_stated(self, ctx: Context, spec: dict) -> dict:
        texts = [ctx.message] + ([ctx.last_user] if ctx.follow_up() else [])
        return noul_answer(0.95 if any(NUMBER.search(t) for t in texts) else 0.05)

    # -------------------------------------------------------------- passages
    def _q_relevant(self, ctx: Context, spec: dict) -> dict:
        state = ctx.state
        return noul_answer(min(1.0, 0.1 + coverage(state.get("query", ""), state.get("passage", ""))))

    def _q_has_answer(self, ctx: Context, spec: dict) -> dict:
        cov = coverage(ctx.state.get("query", ""), ctx.state.get("passage", ""))
        return noul_answer(0.8 if cov >= 0.6 else cov * 0.7)

    def _q_contradicts(self, ctx: Context, spec: dict) -> dict:
        return noul_answer(0.03)

    def _q_claim_support(self, ctx: Context, spec: dict) -> dict:
        options = list(spec["criteria"])
        cov = coverage(ctx.state.get("claim", ""), ctx.state.get("passage", ""))
        return choice_answer(options, {"supports": 1.0} if cov >= 0.5 else {"says_nothing": 1.0})

    # ------------------------------------------------------------------ gate
    def _q_explicit(self, ctx: Context, spec: dict) -> dict:
        request = str(ctx.state.get("request", ""))
        return noul_answer(0.9 if _any(WANTS_CHANGE, request) or "confirm" in request.lower() else 0.2)

    def _q_own_account(self, ctx: Context, spec: dict) -> dict:
        action = ctx.state.get("action") or {}
        own = (ctx.state.get("session") or {}).get("account_id")
        return noul_answer(0.97 if action.get("account_id") in (None, own) else 0.05)

    def _q_impact(self, ctx: Context, spec: dict) -> dict:
        tool = (ctx.state.get("action") or {}).get("tool")
        return score_answer(len(spec["criteria"]), {"book_room": 1.0, "place_hold": 0.3, "add_event": 0.4}.get(tool, 1.0))

    # ----------------------------------------------------------------- events
    def __getattr__(self, name: str):
        if name.startswith("_q_") and name.endswith("_supported"):
            def check(ctx: Context, spec: dict) -> dict:
                value = str(ctx.state.get("field_value") or "").lower().strip()
                text = str(ctx.state.get("transcription") or "").lower()
                if not value:
                    return noul_answer(0.05)
                iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
                if iso:  # a date is supported when its year, day, and month (name or number) appear
                    year, month, day = iso.groups()
                    names = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                             "october", "november", "december"]
                    ok = (year in text and re.search(rf"\b0?{int(day)}\b", text) and
                          (names[int(month) - 1] in text or f"-{month}-" in text or f"/{month}/" in text))
                    return noul_answer(0.93 if ok else 0.12)
                parts = [p for p in re.split(r"[\s,:\-–]+", value) if p]
                found = sum(1 for p in parts if p in text) / max(1, len(parts))
                return noul_answer(0.95 if found >= 0.8 else 0.1 + 0.5 * found)
            return check
        raise AttributeError(name)


def passage_injection(text: str) -> bool:
    return bool(PASSAGE_INJECTION.search(text))
