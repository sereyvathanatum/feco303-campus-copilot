"""The build-path switchboard (docs/implementation-plan.md §8.8, §9.1).

Each `profiles/steps/step-NN.toml` lists the capabilities built so far. Missing
capabilities fall back to the simplest behaviour, so the graph at every step is a
real, smaller chatbot:

* no `decisions`: every message takes the RAG path;
* no `tools`: lookups the knowledge base cannot answer abstain;
* no `memory`: each turn starts a fresh thread;
* no `rag` (steps 1-4): the chat reports which ingestion stage the build has reached.
"""

from __future__ import annotations

from dataclasses import dataclass

STEP_TITLES = {
    1: "Gather sources", 2: "Extract text from PDF and Markdown", 3: "Clean and chunk",
    4: "Embed, store, and verify", 5: "Retrieve and answer: the first chatbot", 6: "Remember the conversation",
    7: "Decide with a System One model", 8: "Call tools: SQLite and public APIs", 9: "Agent loop and safe writes",
    10: "Connect through MCP", 11: "Observe, evaluate, and harden", 12: "Images and the architecture decision",
}


@dataclass(frozen=True)
class Capabilities:
    kb: bool
    rag: bool
    memory: bool
    decisions: bool
    tools: bool
    agent: bool
    writes: bool
    mcp: bool
    evaluation: bool
    guards: bool
    vision: bool

    @classmethod
    def from_profile(cls, profile) -> "Capabilities":
        caps = set(profile.capabilities)
        return cls(**{name: name in caps for name in cls.__dataclass_fields__})

    def enabled(self) -> list[str]:
        return [name for name in self.__dataclass_fields__ if getattr(self, name)]


def step_label(profile) -> str:
    step = profile.step
    if step is None:
        return f"Profile {profile.name}"
    return f"Step {step} of 12: {STEP_TITLES.get(step, '')}"
