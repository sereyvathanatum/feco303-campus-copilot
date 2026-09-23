"""The model-visible window (docs/implementation-plan.md §8.8).

The checkpointer persists the whole thread; every model call receives a slice built
with `trim_messages`: `strategy="last"`, bounded by `memory.window_turns` and
`memory.max_tokens`, keeping the system message and starting on a human turn.
Tokens are counted with the same counter as chunk sizing.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, trim_messages

from ..ingest.tokens import get_counter


@dataclass
class Window:
    messages: list[BaseMessage]
    dropped_messages: int
    dropped_tokens: int
    tokens: int

    def as_dicts(self) -> list[dict]:
        out = []
        for m in self.messages:
            role = "system" if isinstance(m, SystemMessage) else "assistant" if isinstance(m, AIMessage) else "user"
            out.append({"role": role, "content": m.content if isinstance(m.content, str) else str(m.content)})
        return out


def _counter(settings):
    return get_counter(str(settings.profile.get("rag.tokenizer", "auto")), settings.embed_model)


def count_tokens(messages: list[BaseMessage], settings) -> int:
    counter = _counter(settings)
    return sum(counter.count(m.content if isinstance(m.content, str) else str(m.content)) + 4 for m in messages)


def model_window(history: list[BaseMessage], settings, system: str | None = None) -> Window:
    """Trim the earlier turns of a thread (the latest message is added by the caller)."""
    profile = settings.profile
    if not profile.get("memory.enabled", True):
        return Window([], len(history), count_tokens(history, settings), 0)
    turns = int(profile.get("memory.window_turns", 6))
    budget = int(profile.get("memory.max_tokens", 2000))
    messages: list[BaseMessage] = ([SystemMessage(system)] if system else []) + list(history)
    if turns <= 0:
        kept = [m for m in messages if isinstance(m, SystemMessage)]
    else:
        # a turn is a human message plus the reply: keep at most 2 * turns non-system messages
        body = [m for m in messages if not isinstance(m, SystemMessage)][-2 * turns:]
        head = [m for m in messages if isinstance(m, SystemMessage)]
        kept = trim_messages(head + body, strategy="last", token_counter=lambda ms: count_tokens(ms, settings),
                             max_tokens=budget, include_system=True, start_on="human", allow_partial=False)
    body_kept = [m for m in kept if not isinstance(m, SystemMessage)]
    dropped = [m for m in history if m not in body_kept]
    return Window(body_kept, len(dropped), count_tokens(dropped, settings), count_tokens(kept, settings))


def jev_history(history: list[BaseMessage], turns: int = 3) -> list[dict]:
    """The decision model's own short slice: the last three turns, as plain text."""
    out = []
    for m in history[-2 * turns:]:
        role = "assistant" if isinstance(m, AIMessage) else "user"
        out.append({"role": role, "text": m.content if isinstance(m.content, str) else str(m.content)})
    return out


def human(text: str) -> HumanMessage:
    return HumanMessage(text)


def ai(text: str) -> AIMessage:
    return AIMessage(text)
