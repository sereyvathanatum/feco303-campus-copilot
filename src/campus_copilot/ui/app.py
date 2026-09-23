"""Gradio app (docs/implementation-plan.md §8.12).

* Header: the active build-path step and profile, with a profile switcher.
* Chat tab: the conversation with image upload and a demo-account picker; side
  panels Decisions, Sources, Tools, Trace, and Memory; Confirm / Cancel buttons for
  a pending write; a "New thread" button.
* Knowledge Base tab: add documents to the inbox, run the ingestion pipeline whole
  or up to one stage, inspect each stage and document, remove documents, read verify results.
* Retrieval Lab tab: one query through modes × stores side by side, exported as a
  Markdown evidence table. No chat model is involved.

API keys stay server-side; the app binds to 127.0.0.1 unless `--share` is passed.
"""

from __future__ import annotations

import html
import json
import os
import uuid
from pathlib import Path

from .. import config
from ..graph.capabilities import step_label

BANNER = "Illustrative text for a demo system; not official CamTech policy. All people and records are synthetic."
_COPILOTS: dict[str, object] = {}


# ------------------------------------------------------------------ services

def copilot_for(profile: str):
    from ..graph.build import Copilot

    if profile not in _COPILOTS:
        _COPILOTS[profile] = Copilot(config.get_settings(profile))
    return _COPILOTS[profile]


def header_text(profile: str) -> str:
    settings = config.get_settings(profile)
    return (f"### CamTech Campus Copilot\n**{step_label(settings.profile)}** · profile `{profile}` · "
            f"run mode `{settings.run_mode}` · chat `{' -> '.join(settings.chat_providers()) or 'stub'}`")


def new_state(profile: str = "baseline") -> dict:
    settings = config.get_settings(profile)
    return {"profile": profile, "thread": f"ui-{uuid.uuid4().hex[:6]}",
            "account": settings.profile.get("app.account_id", "A0001"), "last": None}


# -------------------------------------------------------------- panel views

def _band_colour(value: float, low: float, high: float) -> str:
    return "#2e7d32" if value >= high else "#f9a825" if value >= low else "#c62828"


def decisions_html(result: dict | None, thresholds: tuple[float, float] = (0.5, 0.8)) -> str:
    if not result or not result.get("decision"):
        return "<p>No decision for this turn (the decisions capability is off at this build step).</p>"
    decision = result["decision"]
    low, high = thresholds
    badge = ' <span style="background:#555;color:#fff;padding:1px 6px;border-radius:4px">STUB</span>' \
        if decision.get("stub") else ""
    rows = [f"<p><b>{html.escape(decision.get('decider', ''))}</b> · {html.escape(str(decision.get('model', '')))} · "
            f"{decision.get('ms', 0):.0f} ms{badge}</p>", "<table style='width:100%;font-size:0.9em'>"]
    for qid, answer in (decision.get("answers") or {}).items():
        if answer.get("type") == "choice":
            value = float(answer.get("confidence") or 0)
            label = f"{html.escape(str(answer.get('choice')))} ({value:.2f})"
        elif answer.get("type") == "noul":
            value = float(answer.get("noul") or 0)
            label = f"{value:.2f}"
        else:
            levels = max(1, len(answer.get("probabilities") or {"0": 0, "1": 0}) - 1)
            value = float(answer.get("score") or 0) / levels
            label = f"{float(answer.get('score') or 0):.2f} of {levels}"
        colour = _band_colour(value, low, high)
        rows.append(f"<tr><td>{html.escape(qid)}</td><td style='width:45%'><div style='background:#ddd;height:10px'>"
                    f"<div style='width:{value * 100:.0f}%;background:{colour};height:10px'></div></div></td>"
                    f"<td>{label}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def sources_markdown(result: dict | None) -> str:
    if not result:
        return ""
    lines = []
    query = result.get("query") or {}
    if query.get("rewritten"):
        lines.append(f"**Query rewritten for retrieval:** `{query['rewritten']}`  \n(original: `{query.get('original')}`)\n")
    for s in result.get("sources") or []:
        judge = s.get("judge")
        verdict = f" · judge relevant {judge.get('relevant', 0):.2f}, injection {judge.get('injection', 0):.2f}" if judge else ""
        signals = s.get("signals") or {}
        ranks = " · ".join(part for part in (
            f"relevance {signals['relevance']:.3f} ({signals.get('reranker')})" if "relevance" in signals else "",
            f"lexical #{signals['lexical_rank']}" if "lexical_rank" in signals else "",
            f"dense #{signals['dense_rank']}" if "dense_rank" in signals else "") if part)
        status = {True: " · sent to the model", False: " · **dropped by the passage filter**"}.get(s.get("in_context"), "")
        lines.append(f"- **#{s.get('rank', '-')} {s['citation']}** · {s['score_type']} {s['score']:.3f} · "
                     f"{s['token_count']} tokens{verdict}{status}" + (f"  \n  {ranks}" if ranks else "") + "\n"
                     f"  > {s['text'][:280].replace(chr(10), ' ')}")
    return "\n".join(lines) or "No sources for this turn."


def tools_json(result: dict | None) -> list:
    if not result:
        return []
    return [{k: c.get(k) for k in ("tool", "args", "ok", "summary", "attribution", "source", "transport", "error", "ms")
             if c.get(k) is not None} for c in result.get("tool_calls") or []]


def trace_rows(copilot, result: dict | None) -> list[list]:
    if not result:
        return []
    rows = []
    for span in copilot.trace(result.get("trace_id")):
        model = span.get("model") or span.get("tool") or span.get("decider") or ""
        tokens = f"{span.get('tokens_in', '')}/{span.get('tokens_out', '')}" if span.get("tokens_in") else ""
        rows.append([span["span"], round(span["ms"], 1), model, tokens, span.get("error", "")])
    return rows


def memory_json(copilot, state: dict) -> dict:
    from ..graph.memory import model_window

    values = copilot.state(state["thread"]) if copilot.caps.memory else {}
    messages = values.get("messages") or []
    window = model_window(messages, copilot.settings)
    return {"thread_id": state["thread"], "account_id": state["account"], "turns": values.get("turn"),
            "slots": values.get("slots") or {}, "messages_stored": len(messages),
            "model_window": window.as_dicts(), "dropped_messages": window.dropped_messages,
            "dropped_tokens": window.dropped_tokens}


# -------------------------------------------------------------- chat handlers

def _panels(copilot, state: dict, result: dict | None):
    thresholds = (copilot.rt.thresholds.confidence_low, copilot.rt.thresholds.confidence_high)
    pending = bool(result and result.get("kind") == "confirm")
    import gradio as gr

    return (decisions_html(result, thresholds), sources_markdown(result), tools_json(result),
            trace_rows(copilot, result), memory_json(copilot, state), gr.update(visible=pending),
            gr.update(visible=pending))


def send(message: dict | str, chat: list, state: dict):
    copilot = copilot_for(state["profile"])
    text = message.get("text", "") if isinstance(message, dict) else str(message)
    files = message.get("files", []) if isinstance(message, dict) else []
    image = files[0] if files else None
    image = image.get("path") if isinstance(image, dict) else image
    if not text.strip() and not image:
        return (chat, state, None, *_panels(copilot, state, state.get("last")))
    result = copilot.ask(text or "Add this to the calendar.", thread_id=state["thread"], account_id=state["account"],
                         image_path=image).model_dump()
    state = {**state, "last": result}
    shown = text + (" 📎" if image else "")
    chat = chat + [{"role": "user", "content": shown}, {"role": "assistant", "content": _reply(result)}]
    return (chat, state, None, *_panels(copilot, state, result))


def _reply(result: dict) -> str:
    suffix = []
    if (result.get("decision") or {}).get("stub"):
        suffix.append("STUB decider")
    if any(str(n).startswith("STUB") for n in result.get("notes") or []):
        suffix.append("STUB model")
    tail = f"\n\n*{result['kind']} · route {result.get('route') or '-'}{' · ' + ', '.join(suffix) if suffix else ''}*"
    return result["answer"] + tail


def resume(confirm: bool, chat: list, state: dict):
    copilot = copilot_for(state["profile"])
    result = copilot.resume(state["thread"], confirm).model_dump()
    state = {**state, "last": result}
    chat = chat + [{"role": "assistant", "content": _reply(result)}]
    return (chat, state, *_panels(copilot, state, result))


def switch_profile(profile: str, state: dict):
    state = {**new_state(profile), "account": state.get("account", "A0001")}
    copilot = copilot_for(profile)
    return (header_text(profile), [], state, *_panels(copilot, state, None))


def new_thread(state: dict):
    state = {**state, "thread": f"ui-{uuid.uuid4().hex[:6]}", "last": None}
    copilot = copilot_for(state["profile"])
    return ([], state, *_panels(copilot, state, None))


def set_account(account: str, state: dict):
    return {**state, "account": account}


# ------------------------------------------------------- knowledge-base tab

def stage_table() -> list[list]:
    from ..ingest import pipeline

    runs = pipeline.list_runs()
    if not runs:
        return []
    run = json.loads((runs[0] / "run.json").read_text(encoding="utf-8"))
    rows = []
    for stage in pipeline.STAGES:
        entry = run["stages"].get(stage, {})
        stats = entry.get("stats") or {}
        summary = pipeline.summary_line(stage, stats) if stats else ""
        warnings = ""
        if stage == "gather":
            warnings = "; ".join(f"{k}: {', '.join(v)}" for k, v in (stats.get("flagged") or {}).items())
        elif stage == "extract":
            warnings = "; ".join(f"{f['source_id']} p.{f['page']}" for f in stats.get("flagged") or [])
        elif stage == "chunk":
            warnings = f"{len(stats.get('over_window') or [])} over window" if stats else ""
        rows.append([stage, entry.get("status", ""), summary, entry.get("ms", ""), warnings[:300]])
    return rows


def run_ingest_ui(until: str, profile: str):
    from ..ingest import pipeline

    log: list[str] = []
    try:
        pipeline.run_ingest(config.get_settings(profile), until=until, echo=log.append)
    except pipeline.IngestError as exc:
        log.append(f"FAILED: {exc}")
    _COPILOTS.clear()  # retrieval reloads the new chunks
    return "\n".join(log), stage_table(), document_choices()


def add_upload(file, licence: str, origin: str):
    from ..ingest import manifest

    if not file:
        return "Choose a PDF or Markdown file first."
    path = Path(file if isinstance(file, str) else file.name)
    try:
        row = manifest.add_document(path, licence=licence or "unknown", origin=origin or "uploaded in the UI")
    except ValueError as exc:
        return str(exc)
    note = " Licence unknown: the document is flagged in every report." if row["licence"] == "unknown" else ""
    return f"Added {row['file']} as `{row['source_id']}`. Run the pipeline to ingest it.{note}"


def document_choices() -> list[str]:
    from ..ingest import store as kb

    conn = kb.connect()
    return [r["source_id"] for r in conn.execute("SELECT source_id FROM documents WHERE status = 'ingested' ORDER BY source_id")]


def document_view(source_id: str) -> str:
    from ..ingest import pipeline

    if not source_id:
        return ""
    parts = [f"## {source_id}"]
    _, extracted = pipeline.find_artifact("extract", source_id)
    _, cleaned = pipeline.find_artifact("clean", source_id)
    _, chunks = pipeline.find_artifact("chunk", source_id)
    for unit in (extracted or [])[:6]:
        where = f"page {unit['page']}" if unit.get("page") else "body"
        flags = f" — flags: {'; '.join(unit['flags'])}" if unit.get("flags") else ""
        parts.append(f"**Extracted, {where}** ({unit['chars']} characters, script {unit['script']}){flags}\n\n"
                     f"```\n{unit['text'][:600]}\n```")
    for unit in (cleaned or [])[:6]:
        if unit.get("samples"):
            parts.append(f"**Cleaning removed ({unit.get('page') or 'body'}):** {unit['removed']} e.g. {unit['samples'][:3]}")
    if chunks:
        parts.append(f"**{len(chunks)} chunks**")
        for c in chunks[:12]:
            where = f"p.{c['page']}" if c.get("page") else f"§ {c['section']}"
            parts.append(f"- `{c['chunk_id']}` {where} · {c['token_count']} tokens · {c['language']}: "
                         f"{c['text'][:160].replace(chr(10), ' ')}")
    return "\n\n".join(parts)


def remove_doc(source_id: str) -> str:
    from ..ingest import pipeline

    return pipeline.remove_document(source_id) if source_id else "Choose a document first."


def verify_table() -> list[list]:
    from ..ingest import pipeline

    _, data = pipeline.find_artifact("verify")
    if not data:
        return []
    return [[r["question"], r["source_id"], r.get("page") or r.get("section_contains") or "", "hit" if r["hit"] else "MISS",
             ", ".join(r["top"])] for r in data.get("results", [])]


# ------------------------------------------------------------ retrieval lab

def run_lab(query: str, modes: list[str], stores: list[str], k: int, profile: str):
    from ..rag.compare import compare

    if not query.strip():
        return "Enter a query.", ""
    comparison = compare(query, config.get_settings(profile), modes=modes or None, stores=stores or None, k=int(k))
    table = comparison.markdown()
    return table, table


# --------------------------------------------------------------------- build

def build_app(profile: str | None = None):
    import gradio as gr

    from ..rag.retrieve import MODES

    profile = profile or os.environ.get("COPILOT_PROFILE") or "baseline"
    connection_accounts = _accounts()
    with gr.Blocks(title="CamTech Campus Copilot") as app:
        state = gr.State(new_state(profile))
        with gr.Row():
            header = gr.Markdown(header_text(profile))
            profile_box = gr.Dropdown(config.list_profiles(), value=profile, label="Profile / build step", scale=0)
        with gr.Tabs():
            with gr.Tab("Chat"):
                with gr.Row():
                    with gr.Column(scale=3):
                        chat = gr.Chatbot(height=520, label="Conversation")
                        box = gr.MultimodalTextbox(placeholder="Ask a campus question or attach a notice photo",
                                                   file_types=["image"], label="Message")
                        with gr.Row():
                            confirm_btn = gr.Button("Confirm", variant="primary", visible=False)
                            cancel_btn = gr.Button("Cancel", visible=False)
                            thread_btn = gr.Button("New thread")
                            account_box = gr.Dropdown(connection_accounts, value=connection_accounts[0],
                                                      label="Demo account")
                    with gr.Column(scale=2):
                        with gr.Tabs():
                            with gr.Tab("Decisions"):
                                decisions = gr.HTML()
                            with gr.Tab("Sources"):
                                sources = gr.Markdown()
                            with gr.Tab("Tools"):
                                tools = gr.JSON()
                            with gr.Tab("Trace"):
                                trace = gr.Dataframe(headers=["span", "ms", "model or tool", "tokens in/out", "error"])
                            with gr.Tab("Memory"):
                                memory = gr.JSON()
            with gr.Tab("Knowledge Base"):
                with gr.Row():
                    upload = gr.File(label="Add a PDF or Markdown document to data/inbox/", file_types=[".pdf", ".md"])
                    with gr.Column():
                        licence = gr.Textbox(label="Licence", placeholder="for example CC-BY-4.0")
                        origin = gr.Textbox(label="Origin", placeholder="URL or source of the document")
                        add_btn = gr.Button("Add document")
                add_msg = gr.Markdown()
                with gr.Row():
                    until = gr.Dropdown(["gather", "extract", "clean", "chunk", "embed", "store", "verify"],
                                        value="verify", label="Run the pipeline up to")
                    run_btn = gr.Button("Run ingestion", variant="primary")
                run_log = gr.Textbox(label="Run log", lines=8)
                stages = gr.Dataframe(stage_table(), headers=["stage", "status", "summary", "ms", "warnings"],
                                      label="Stages")
                with gr.Row():
                    doc = gr.Dropdown(document_choices(), label="Document")
                    remove_btn = gr.Button("Remove document")
                remove_msg = gr.Markdown()
                doc_view = gr.Markdown()
                verify = gr.Dataframe(verify_table(), headers=["probe", "source", "page or section", "result", "top-k"],
                                      label="Verify: probe hit@k")
            with gr.Tab("Retrieval Lab"):
                query = gr.Textbox(label="Query", value="What is the penalty for late assignments?")
                with gr.Row():
                    modes = gr.CheckboxGroup(list(MODES), value=["lexical", "dense", "hybrid"], label="Retrieval modes")
                    stores = gr.CheckboxGroup(["sqlite", "sqlite_vec", "chroma"], value=["sqlite", "sqlite_vec"],
                                              label="Stores")
                    k = gr.Slider(1, 10, value=4, step=1, label="top-k")
                lab_btn = gr.Button("Compare", variant="primary")
                lab_table = gr.Markdown()
                evidence = gr.Code(label="Copy as evidence table (Markdown)", language="markdown")
        gr.Markdown(f"<small>{BANNER}</small>")

        panels = [decisions, sources, tools, trace, memory, confirm_btn, cancel_btn]
        box.submit(send, [box, chat, state], [chat, state, box, *panels])
        confirm_btn.click(lambda c, s: resume(True, c, s), [chat, state], [chat, state, *panels])
        cancel_btn.click(lambda c, s: resume(False, c, s), [chat, state], [chat, state, *panels])
        thread_btn.click(new_thread, [state], [chat, state, *panels])
        account_box.change(set_account, [account_box, state], [state])
        profile_box.change(switch_profile, [profile_box, state], [header, chat, state, *panels])
        add_btn.click(add_upload, [upload, licence, origin], [add_msg])
        run_btn.click(lambda u, s: run_ingest_ui(u, s["profile"]), [until, state], [run_log, stages, doc]).then(
            verify_table, None, [verify])
        doc.change(document_view, [doc], [doc_view])
        remove_btn.click(remove_doc, [doc], [remove_msg])
        lab_btn.click(lambda q, m, st, kk, s: run_lab(q, m, st, kk, s["profile"]), [query, modes, stores, k, state],
                      [lab_table, evidence])
    return app


def _accounts() -> list[str]:
    from ..db import connection

    try:
        return connection.list_account_ids()
    except Exception:
        return ["A0001"]


def launch(profile: str | None = None, share: bool = False, port: int | None = None) -> None:
    app = build_app(profile)
    app.launch(server_name="127.0.0.1", server_port=port, share=share, inbrowser=False)
