"""One model interface for the whole app: live providers in order, then the stub.

`get_llm(settings, role)` returns an `LLM` whose task methods (grounded answer,
condense, final answer, agent step, image reading, judging) build prompts for a
live model and structured payloads for the stub. When every live provider fails,
the stub answers and the reply is labelled `STUB (<provider> unavailable)`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..schemas import ABSTAIN_TEXT, Citation, GroundedAnswer
from . import prompts
from .nim import LLMError, LLMReply, OpenAICompatClient, image_part, parse_json_object
from .stub import StubClient


@dataclass
class CallLog:
    replies: list[LLMReply] = field(default_factory=list)

    @property
    def tokens_in(self) -> int:
        return sum(r.tokens_in for r in self.replies)

    @property
    def tokens_out(self) -> int:
        return sum(r.tokens_out for r in self.replies)


class LLM:
    def __init__(self, clients: list, settings, role: str = "chat") -> None:
        self.clients = clients
        self.settings = settings
        self.role = role
        self.log = CallLog()

    @property
    def label(self) -> str:
        live = [c.name for c in self.clients if not isinstance(c, StubClient)]
        return " -> ".join(live + ["stub"]) if live else "stub"

    @property
    def is_stub(self) -> bool:
        return all(isinstance(c, StubClient) for c in self.clients)

    # ------------------------------------------------------------------ core
    def complete(self, messages: list[dict], *, task: str, payload: dict | None = None, max_tokens: int | None = None,
                 temperature: float | None = None, tools: list[dict] | None = None, json_mode: bool = False) -> LLMReply:
        profile = self.settings.profile
        max_tokens = max_tokens or self.settings.max_tokens
        temperature = float(profile.get("llm.temperature", 0.0)) if temperature is None else temperature
        failures: list[str] = []
        for client in self.clients:
            try:
                if isinstance(client, StubClient):
                    reply = client.complete(messages, task=task, payload=payload)
                    if failures:
                        reply.notes = [f"STUB ({', '.join(f.split(':')[0] for f in failures)} unavailable)"]
                else:
                    reply = client.complete(messages, max_tokens=max_tokens, temperature=temperature, tools=tools,
                                            json_mode=json_mode)
                    reply.notes.extend(f"fallback: {f}" for f in failures)
                self.log.replies.append(reply)
                return reply
            except LLMError as exc:
                failures.append(f"{getattr(client, 'provider', 'model')}: {exc}")
        raise LLMError("; ".join(failures))

    def _system(self) -> dict:
        return {"role": "system", "content": prompts.SYSTEM_PROMPT}

    # ----------------------------------------------------------------- tasks
    def grounded_answer(self, question: str, passages: list[dict], history: list[dict] | None = None,
                        original: str | None = None) -> tuple[GroundedAnswer, LLMReply]:
        """`passages`: dicts with source_id, page, section, text. `history`: trimmed model window."""
        profile = self.settings.profile
        sources = "\n".join(
            f'<source source_id="{p["source_id"]}"' + (f' page="{p["page"]}"' if p.get("page") else "")
            + (f' section="{p["section"]}"' if p.get("section") and not p.get("page") else "")
            + f'>{p["text"]}</source>' for p in passages)
        messages = [self._system()]
        if profile.get("llm.prompt_style", "few_shot") == "few_shot":
            for shot in prompts.FEW_SHOT:
                messages.append({"role": "user", "content": f"<sources>\n{shot['sources']}\n</sources>\n"
                                                            f"question: {shot['question']}"})
                messages.append({"role": "assistant", "content": shot["reply"]})
        messages.extend(history or [])
        asked = original if original and original != question else question
        extra = f"\nsearch_query: {question}" if asked != question else ""
        structured = bool(profile.get("llm.structured_output", True))
        instructions = prompts.GROUNDED_INSTRUCTIONS if structured else (
            "Answer `question` from <sources> only, citing each fact.")
        messages.append({"role": "user", "content": f"{instructions}\n<sources>\n{sources}\n</sources>\n"
                                                    f"question: {asked}{extra}"})
        reply = self.complete(messages, task="grounded_answer", payload={"question": question, "passages": passages},
                              json_mode=structured)
        return self._parse_grounded(reply, passages, structured), reply

    def _parse_grounded(self, reply: LLMReply, passages: list[dict], structured: bool) -> GroundedAnswer:
        known = {(p["source_id"], p.get("page"), p.get("section")) for p in passages}
        data = parse_json_object(reply.text) if structured else None
        if data is None:
            text = reply.text.strip()
            if ABSTAIN_TEXT.rstrip(".") in text:
                return GroundedAnswer(answer=ABSTAIN_TEXT, abstained=True)
            reply.notes.append("schema failure: reply was not valid JSON" if structured else "free-text reply")
            cited = [Citation(source_id=s, page=p, section=sec) for s, p, sec in known
                     if (f"[{s} p.{p}]" in text if p else f"[{s} § {sec}]" in text)]
            return GroundedAnswer(answer=text, citations=cited, abstained=False)
        try:
            answer = GroundedAnswer.model_validate(data)
        except ValidationError:
            reply.notes.append("schema failure: JSON did not match GroundedAnswer")
            return GroundedAnswer(answer=str(data.get("answer", ABSTAIN_TEXT)), abstained=True)
        if ABSTAIN_TEXT.rstrip(".") in answer.answer:
            answer.abstained = True
        valid = []
        for c in answer.citations:
            match = next((k for k in known if k[0] == c.source_id and (c.page is None or k[1] == c.page)
                          and (c.section is None or k[2] == c.section or not k[2])), None)
            if match:
                valid.append(Citation(source_id=match[0], page=match[1], section=match[2]))
            else:
                reply.notes.append(f"dropped citation to a passage that was not provided: {c.source_id}")
        answer.citations = valid
        if answer.abstained:
            answer.answer, answer.citations = ABSTAIN_TEXT, []
        return answer

    def condense(self, message: str, history: list[dict]) -> tuple[str, LLMReply]:
        lines = "\n".join(f"{m['role']}: {m['content']}" for m in history)
        messages = [{"role": "system", "content": prompts.CONDENSE_TEMPLATE},
                    {"role": "user", "content": f"history:\n{lines}\n\nmessage: {message}"}]
        reply = self.complete(messages, task="condense", payload={"message": message, "history": history},
                              max_tokens=64, temperature=0.0)
        return reply.text.strip().strip('"').splitlines()[0] if reply.text.strip() else message, reply

    def generate_probe(self, title: str, text: str) -> str:
        messages = [{"role": "system", "content": prompts.PROBE_TEMPLATE},
                    {"role": "user", "content": f"title: {title}\nexcerpt: {text[:1500]}"}]
        return self.complete(messages, task="probe", payload={"title": title, "text": text}, max_tokens=64).text.strip()

    def small_reply(self, message: str) -> LLMReply:
        messages = [{"role": "system", "content": prompts.SMALL_TALK_TEMPLATE}, {"role": "user", "content": message}]
        return self.complete(messages, task="small_reply", payload={"message": message}, max_tokens=120)

    def final_answer(self, message: str, tool_results: list[dict]) -> LLMReply:
        blocks = "\n".join(prompts.TOOL_RESULT_WRAPPER.format(
            source=r.get("tool", "tool"), content=json.dumps({k: r.get(k) for k in ("summary", "data", "attribution")},
                                                             ensure_ascii=False, default=str)) for r in tool_results)
        messages = [{"role": "system", "content": prompts.FINAL_ANSWER_TEMPLATE},
                    {"role": "user", "content": f"message: {message}\n{blocks}"}]
        return self.complete(messages, task="final_answer", payload={"message": message, "tool_results": tool_results},
                             max_tokens=300)

    def agent_step(self, message: str, tools: list[dict], observations: list[dict],
                   candidate_tools: list[dict] | None = None, history: list[dict] | None = None) -> tuple[dict | None, LLMReply]:
        obs = "\n".join(prompts.TOOL_RESULT_WRAPPER.format(source=o["tool"], content=json.dumps(
            {"args": o.get("args"), "summary": o.get("summary"), "ok": o.get("ok")}, ensure_ascii=False, default=str))
            for o in observations)
        messages = [{"role": "system", "content": prompts.AGENT_JSON_PROTOCOL}, *(history or []),
                    {"role": "user", "content": f"message: {message}\ntools: {json.dumps(tools, ensure_ascii=False)}\n"
                                                f"observations:\n{obs or '(none)'}"}]
        reply = self.complete(messages, task="agent_step", payload={"message": message, "observations": observations,
                                                                     "candidate_tools": candidate_tools or []},
                              max_tokens=300, json_mode=True)
        return parse_json_object(reply.text), reply

    def native_tool_step(self, message: str, tool_schemas: list[dict], observations: list[dict],
                         candidate_tools: list[dict] | None = None) -> LLMReply:
        messages = [{"role": "system", "content": prompts.SYSTEM_PROMPT}, {"role": "user", "content": message}]
        for o in observations:
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": o.get("call_id", o["tool"]), "type": "function",
                 "function": {"name": o["tool"], "arguments": json.dumps(o.get("args", {}))}}]})
            messages.append({"role": "tool", "tool_call_id": o.get("call_id", o["tool"]),
                             "content": prompts.TOOL_RESULT_WRAPPER.format(source=o["tool"], content=o.get("summary"))})
        reply = self.complete(messages, task="agent_step", payload={"message": message, "observations": observations,
                                                                     "candidate_tools": candidate_tools or []},
                              tools=tool_schemas, max_tokens=300)
        if reply.stub:  # the stub speaks the JSON protocol; translate to a native tool call
            data = parse_json_object(reply.text) or {}
            if data.get("action") == "call_tool":
                reply.tool_calls = [{"id": data["tool"], "tool": data["tool"], "args": data.get("args", {})}]
                reply.text = ""
            else:
                reply.text = data.get("answer", reply.text)
        return reply

    def read_image(self, image_path: str, today: str) -> tuple[dict, LLMReply]:
        content = [{"type": "text", "text": f"{prompts.IMAGE_TEMPLATE}\ntoday: {today}"}, image_part(image_path)]
        reply = self.complete([{"role": "user", "content": content}], task="read_image",
                              payload={"image_path": image_path, "today": today}, max_tokens=600, json_mode=True)
        return parse_json_object(reply.text) or {"transcription": reply.text, "event": {}}, reply

    def judge_faithfulness(self, answer: str, passages: list[str]) -> tuple[dict, LLMReply]:
        messages = [{"role": "system", "content": prompts.JUDGE_RUBRIC},
                    {"role": "user", "content": "passages:\n" + "\n---\n".join(passages) + f"\n\nanswer: {answer}"}]
        reply = self.complete(messages, task="judge", payload={"answer": answer, "passages": passages},
                              max_tokens=120, json_mode=True)
        return parse_json_object(reply.text) or {"score": None, "reason": "unparseable judge reply"}, reply

    def route_json(self, state: dict, questions: dict) -> tuple[dict | None, LLMReply]:
        spec = json.dumps(questions, ensure_ascii=False)
        messages = [{"role": "system", "content": (
            "Answer every question in `questions` about `state`. Return one JSON object keyed by question ID. "
            'For a "choice": {"type": "choice", "choice": <option>, "confidence": <0-1>, "probabilities": {...}}; '
            'for a "noul": {"type": "noul", "noul": <0-1>}; for a "score": {"type": "score", "score": <0-1>, '
            '"confidence": <0-1>}. Output only the JSON object.')},
                    {"role": "user", "content": f"state: {json.dumps(state, ensure_ascii=False)}\nquestions: {spec}"}]
        reply = self.complete(messages, task="router", payload={"state": state, "questions": questions},
                              max_tokens=900, json_mode=True)
        return parse_json_object(reply.text), reply


def _live_clients(settings, role: str) -> list:
    clients = []
    thinking = bool(settings.profile.get("llm.thinking", False))
    for provider in settings.chat_providers():
        if provider == "google":
            models = [settings.google_small_model] if role == "small" else [settings.google_chat_model,
                                                                            settings.google_small_model]
            for model in dict.fromkeys(models):  # the smaller Gemma 4 also backs up the main one under load
                clients.append(OpenAICompatClient("google", settings.google_base_url, settings.gemini_api_key, model,
                                                  timeout=settings.google_timeout, thinking=thinking))
        elif provider == "nim":
            model = settings.small_model if role == "small" else settings.chat_model
            key = settings.nemotron_api_key if role == "small" else settings.nvidia_api_key
            clients.append(OpenAICompatClient("nim", settings.nvidia_base_url, key, model,
                                              timeout=settings.nim_timeout, thinking=thinking))
    return clients


def get_llm(settings, role: str = "chat") -> LLM:
    """`role`: "chat" (main model, also vision) or "small" (condense, small talk, model routing)."""
    clients = _live_clients(settings, role)
    reason = "offline mode" if not clients else "fallback"
    return LLM([*clients, StubClient(reason)], settings, role)
