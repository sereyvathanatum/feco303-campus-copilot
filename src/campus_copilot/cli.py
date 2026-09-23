"""Command-line interface: `python -m campus_copilot.cli <command>`.

Every command lives here as a small function; heavy modules load lazily so
`cli check` and `cli init-env` start fast.
"""

from __future__ import annotations

import argparse
import sys

from . import config


def _settings(args):
    overrides = {}
    for item in getattr(args, "set", None) or []:
        key, _, value = item.partition("=")
        overrides[key.strip()] = _coerce(value.strip())
    return config.get_settings(getattr(args, "profile", None), overrides)


def _coerce(value: str):
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


# ------------------------------------------------------------------ P0 commands

def cmd_init_env(args) -> int:
    path, created = config.init_env_file()
    if created:
        print(f"Created {path} from .env.example. Replace the placeholder keys to leave offline mode.")
    else:
        print(f"{path} already exists; left unchanged.")
    return 0


def cmd_check(args) -> int:
    from .diagnostics import run_check

    print(run_check(_settings(args), network=not args.no_network))
    return 0


# ------------------------------------------------------------------ P1 commands

def cmd_seed(args) -> int:
    from .db import connection, seed

    path = seed.build(connection.db_path())
    print(f"Campus DB built at {path}")
    for table, count in seed.table_counts(path).items():
        print(f"  {table:<14} {count:>4} rows")
    print(f"Content hash: {seed.content_hash(path)}")
    return 0


# ------------------------------------------------------------------ P2 commands

def cmd_ingest(args) -> int:
    from pathlib import Path

    from .ingest import manifest, pipeline

    if getattr(args, "ingest_action", None) == "add":
        settings = _settings(args)
        if args.url:
            row = manifest.download_document(args.url, licence=args.licence, origin=args.origin or "",
                                             contact=settings.http_contact)
        elif args.file:
            row = manifest.add_document(Path(args.file), licence=args.licence, origin=args.origin or "",
                                        title=args.title or "", language=args.language or "")
        else:
            print("ingest add needs FILE or --url URL")
            return 2
        print(f"Added {row['file']} as {row['source_id']} (licence: {row['licence']}); run `cli ingest` next.")
        return 0
    if args.show:
        return pipeline.show(args.show, args.doc)
    if args.remove:
        print(pipeline.remove_document(args.remove))
        return 0
    settings = _settings(args)
    try:
        state = pipeline.run_ingest(settings, until=args.until, store=args.store, resume=args.resume,
                                    gen_probes=args.gen_probes)
    except pipeline.IngestError as exc:
        print(f"ingest failed: {exc}")
        return 1
    verify = state["stages"].get("verify", {})
    if verify.get("status") == "done" and not verify["stats"]["passed"]:
        return 1
    return 0


def cmd_retrieve(args) -> int:
    settings = _settings(args)
    if args.compare:
        from .rag.compare import compare

        modes = args.modes.split(",") if args.modes else None
        stores = args.stores.split(",") if args.stores else None
        print(compare(args.query, settings, modes=modes, stores=stores, k=args.k).markdown())
        return 0
    from .rag.retrieve import retrieve

    result = retrieve(args.query, settings, mode=args.mode, store=args.store, k=args.k)
    print(f"mode {result.mode} @ {result.store}; {result.candidates} candidates -> {len(result.chunks)} kept; "
          f"{result.latency_ms:.0f} ms; notes: {'; '.join(result.notes) or '-'}")
    for c in result.chunks:
        _print_chunk(c.as_dict(), args.full)
    for c in result.dropped:
        print(f"  dropped: {c.citation} judge {c.judge}")
    return 0


def _signal_text(source: dict) -> str:
    s = source.get("signals") or {}
    parts = []
    if "relevance" in s:
        parts.append(f"relevance {s['relevance']:.3f} ({s.get('reranker', 'rerank')})")
    if "lexical_rank" in s:
        parts.append(f"lexical #{s['lexical_rank']} bm25 {s['bm25']:.2f}")
    if "dense_rank" in s:
        parts.append(f"dense #{s['dense_rank']} cos {s['cosine']:.3f}")
    if "rrf" in s:
        parts.append(f"rrf {s['rrf']:.4f}")
    if "first_stage_rank" in s:
        parts.append(f"first-stage #{s['first_stage_rank']}")
    judge = source.get("judge")
    if judge:
        parts.append(f"judge relevant {judge.get('relevant', 0):.2f} has_answer {judge.get('has_answer', 0):.2f}")
    return " · ".join(parts)


def _print_chunk(source: dict, full: bool = False) -> None:
    marker = {True: "used", False: "DROPPED", None: ""}[source.get("in_context")]
    print(f"  #{source.get('rank', '-')} {source['citation']}  {source['score_type']} {source['score']:.4f}  "
          f"{source['token_count']} tok  {marker}".rstrip())
    signals = _signal_text(source)
    if signals:
        print(f"      {signals}")
    text = source["text"] if full else source["text"][:400] + (" …" if len(source["text"]) > 400 else "")
    for line in text.splitlines():
        print(f"      | {line}")


def _print_chunks(result, full: bool = False) -> None:
    if not result.sources:
        print("  chunks: none retrieved for this turn")
        return
    used = sum(1 for s in result.sources if s.get("in_context", True))
    print(f"  chunks: {len(result.sources)} retrieved, {used} sent to the model (best first)")
    for source in result.sources:
        _print_chunk(source, full)


# ------------------------------------------------------------------ P3 commands

def _bar(value: float, width: int = 20) -> str:
    filled = int(round(max(0.0, min(1.0, value)) * width))
    return "#" * filled + "." * (width - filled)


def cmd_decide(args) -> int:
    from .db import connection, queries
    from .decisions import policy
    from .decisions import questions as qcat
    from .decisions.base import get_decider

    settings = _settings(args)
    conn = connection.read_connection()
    account = args.account or settings.profile.get("app.account_id", "A0001")
    catalogue = qcat.turn_catalogue(queries.course_codes(conn))
    decider = get_decider(settings, kind=args.decider)
    state = qcat.turn_state(args.message, [], account, queries.enrolled_courses(conn, account))
    decision = decider.decide(state, qcat.wire(catalogue))
    badge = " [STUB]" if decision.stub else ""
    print(f"decider: {decider.name}{badge}  model: {decision.model}  {decision.ms:.0f} ms  usage: {decision.usage}")
    if not decision.ok:
        print(f"request failed: HTTP {decision.status}: {decision.error}")
        return 1
    for qid, question in catalogue.items():
        answer = decision.get(qid)
        if question.type == "noul":
            value = float(answer.get("noul", 0))
            print(f"  {qid:<18} noul   {value:5.2f} {_bar(value)}")
        elif question.type == "choice":
            print(f"  {qid:<18} choice {answer.get('choice')} (confidence {float(answer.get('confidence', 0)):.2f})")
            probs = sorted((answer.get("probabilities") or {}).items(), key=lambda kv: -kv[1])[:4]
            for option, p in probs:
                print(f"      {option:<16} {p:5.2f} {_bar(p)}")
        else:
            levels = len(question.spec["criteria"]) - 1
            value = float(answer.get("score", 0))
            print(f"  {qid:<18} score  {value:5.2f} of {levels} {_bar(value / levels if levels else 0)}")
    action = policy.decide_action(decision, policy.Thresholds.from_profile(settings.profile),
                                  offices=settings.profile.get("campus.offices", {}))
    print(f"policy -> {action.kind}: {action.reason}" + (f"\n  reply: {action.reply}" if action.reply else ""))
    return 0


def cmd_jev_smoke(args) -> int:
    from .decisions.jev import smoke

    settings = _settings(args)
    if not settings.has_jev:
        print("TYPESAFE_API_KEY is missing or a placeholder; set it in .env to call Jev.")
        return 1
    decision, info = smoke(settings)
    if not decision.ok:
        print(f"Jev request failed: HTTP {decision.status}: {decision.error}")
        return 1
    urgency = decision.noul("urgency")
    print(f"noul (urgency): {urgency:.2f}")
    print(f"model: {decision.model}")
    print(f"usage: {decision.usage}")
    print(f"latency: {info['ms']:.0f} ms")
    return 0


# ------------------------------------------------------------------ P5 commands

def _print_turn(result, copilot, show_trace: bool = True, show_chunks: bool = False, full: bool = False) -> None:
    badge = " [STUB]" if (result.decision or {}).get("stub") else ""
    print(f"\n{result.answer}\n")
    route = f"route {result.route}" if result.route else "no route"
    print(f"  [{result.kind}] {route}{badge}  thread {result.thread_id}  trace {result.trace_id}")
    if (result.query or {}).get("rewritten"):
        print(f"  query rewritten: {result.query['rewritten']!r} (original kept: {result.query['original']!r})")
    for call in result.tool_calls:
        print(f"  tool {call['tool']} {call.get('args')} -> {'ok' if call.get('ok') else 'error'}"
              f"{' (' + call['source'] + ')' if call.get('source') else ''}")
    for note in result.notes:
        if note.startswith(("STUB", "fallback", "MCP", "agent stopped", "passage filter", "answer check")):
            print(f"  note: {note}")
    if show_trace:
        spans = copilot.trace(result.trace_id)
        timeline = ", ".join(f"{s['span']} {s['ms']:.0f}ms" for s in spans if s["span"] not in ("turn",))
        print(f"  trace: {timeline}")
    if show_chunks:
        _print_chunks(result, full)


def _copilot(args, step: int | None = None):
    from .graph.build import Copilot

    profile = config.step_profile_name(step) if step else getattr(args, "profile", None)
    overrides = {}
    for item in getattr(args, "set", None) or []:
        key, _, value = item.partition("=")
        overrides[key.strip()] = _coerce(value.strip())
    return Copilot(config.get_settings(profile, overrides))


def _confirm_loop(copilot, result):
    while result.kind == "confirm":
        answer = input(f"{result.answer} [y/n] ").strip().lower()
        result = copilot.resume(result.thread_id, answer in {"y", "yes"})
        _print_turn(result, copilot)
    return result


def cmd_ask(args) -> int:
    copilot = _copilot(args)
    try:
        result = copilot.ask(args.message, thread_id=args.thread, account_id=args.account, image_path=args.image)
        _print_turn(result, copilot, show_chunks=args.show_chunks, full=args.full)
        if result.kind == "confirm":
            if args.yes or args.no:
                _print_turn(copilot.resume(result.thread_id, bool(args.yes)), copilot)
            elif sys.stdin.isatty():
                _confirm_loop(copilot, result)
    finally:
        copilot.close()
    return 0


def _chat(copilot, args) -> int:
    import uuid

    from .graph.capabilities import step_label

    thread = args.thread or f"chat-{uuid.uuid4().hex[:6]}"
    account = args.account or copilot.settings.profile.get("app.account_id", "A0001")
    print(f"{step_label(copilot.settings.profile)} | mode {copilot.settings.run_mode} | account {account} | "
          f"thread {thread}")
    print("Commands: /thread (new thread), /trace (last trace), /chunks (toggle the retrieved-chunk view), "
          "/verbose (toggle step logs), /profile NAME, /quit")
    last = None
    show_chunks, full = bool(getattr(args, "show_chunks", False)), bool(getattr(args, "full", False))
    while True:
        try:
            message = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message in {"/quit", "/exit"}:
            break
        if message == "/thread":
            thread = f"chat-{uuid.uuid4().hex[:6]}"
            print(f"new thread {thread}")
            continue
        if message == "/chunks":
            show_chunks = not show_chunks
            print(f"chunk view {'on' if show_chunks else 'off'}")
            if show_chunks and last is not None:
                _print_chunks(last, full)
            continue
        if message == "/verbose":
            import logging

            logger = logging.getLogger("campus_copilot")
            logger.setLevel(logging.WARNING if logger.level <= logging.INFO else logging.INFO)
            print(f"step logs {'on' if logger.level <= logging.INFO else 'off'}")
            continue
        if message == "/trace":
            for span in copilot.trace(last.trace_id) if last else []:
                extras = {k: v for k, v in span.items() if k in ("tool", "action", "model", "tokens_in", "reason")}
                print(f"  {span['span']:<16} {span['ms']:>7.1f} ms {extras}")
            continue
        if message.startswith("/profile"):
            name = message.split(maxsplit=1)[1] if " " in message else "baseline"
            copilot.close()
            from .graph.build import Copilot

            copilot = Copilot(config.get_settings(name))
            print(f"profile {name}")
            continue
        last = copilot.ask(message, thread_id=thread, account_id=account)
        _print_turn(last, copilot, show_trace=False, show_chunks=show_chunks, full=full)
        last = _confirm_loop(copilot, last)
    copilot.close()
    return 0


def cmd_chat(args) -> int:
    return _chat(_copilot(args), args)


def cmd_demo(args) -> int:
    from .graph.demo import demo_settings, run_demo
    from .graph.build import Copilot

    profile = config.step_profile_name(args.step_n) if getattr(args, "step_n", None) else args.profile
    copilot = Copilot(demo_settings(profile))
    try:
        board = run_demo(copilot, confirm=args.confirm)
    finally:
        copilot.close()
    print(board.render())
    if board.step:
        expected = board.expected(board.step)
        verdict = "matches" if board.passed == expected else "DIFFERS FROM"
        print(f"\nScoreboard {verdict} the expected turns for step {board.step}: {expected}")
        return 0 if board.passed == expected else 1
    return 0 if len(board.passed) == len(board.outcomes) else 1


def cmd_step(args) -> int:
    from .graph.capabilities import step_label

    step = args.n
    print(step_label(config.load_profile(config.step_profile_name(step))))
    if args.check:
        import pytest

        path = config.REPO_ROOT / "tests" / "steps" / f"test_step_{step:02d}.py"
        return int(pytest.main(["-q", str(path)]))
    if args.chat:
        return _chat(_copilot(args, step), args)
    args.step_n = step
    return cmd_demo(args)


def cmd_tools(args) -> int:
    from .tools.registry import registry

    for spec in registry().specs(include_sql=True):
        params = spec.parameters().get("properties", {})
        flag = "W" if spec.write else "R"
        print(f"  [{flag}] {spec.name:<17} {spec.kind:<3} {spec.description}")
        print(f"        args: {', '.join(params) or '(none)'}   source: {spec.source}")
    return 0


# ------------------------------------------------------------------ P6 commands

def cmd_mcp_serve(args) -> int:
    """Run one MCP server over stdio (for MCP Inspector: `mcp dev` or `npx @modelcontextprotocol/inspector`)."""
    from .mcp import campus_server, public_server
    from .mcp.common import serve

    print(f"campus-copilot {args.server} MCP server on stdio", file=sys.stderr)
    serve((campus_server if args.server == "campus" else public_server).server())
    return 0


# ------------------------------------------------------------------ P8 commands

def cmd_eval(args) -> int:
    from .evaluation.judges import disagreement_report
    from .evaluation.runner import run_eval

    settings = _settings(args)
    if args.vision:
        from .evaluation.vision import render, run_vision_eval
        from .graph.nodes import Runtime

        print(render(run_vision_eval(Runtime(settings))))
        return 0
    run = run_eval(settings, subset=args.subset, judges=args.judges, echo=print if args.verbose else None)
    print(run.report())
    if args.judges:
        print("\nJudge disagreements (two points or more):")
        print(disagreement_report(run.rows))
    return 0


def cmd_trace_report(args) -> int:
    from .observability.report import build_report, load_spans, render

    settings = _settings(args)
    turns = load_spans(last=args.last)
    if not turns:
        print("No traces yet: run `cli demo` or `cli ask` first.")
        return 1
    report = build_report(turns, settings.profile.get("prices", {}) or {})
    print(render(report) if not args.json else __import__("json").dumps(report, indent=2))
    return 0


# ------------------------------------------------------------------ P7 commands

def cmd_ui(args) -> int:
    from .ui.app import launch

    launch(args.profile, share=args.share, port=args.port)
    return 0


# ----------------------------------------------------------------------- parser

def _log_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("-v", "--verbose", dest="log_verbosity", action="count", default=0,
                   help="verbose logs on stderr (-v, -vv); same as the global flag")


def _chunk_flags(p: argparse.ArgumentParser) -> None:
    _log_flags(p)
    p.add_argument("--show-chunks", action="store_true",
                   help="after each answer, list the retrieved chunks: rank, scores, and whether they reached the model")
    p.add_argument("--full", action="store_true", help="with --show-chunks: print each chunk's full text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="campus_copilot.cli", description="CamTech Campus Copilot")
    parser.add_argument("--profile", help="profile name in profiles/ (default: COPILOT_PROFILE or baseline)")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE",
                        help="override one profile key, for example --set rag.top_k=6")
    parser.add_argument("-v", "--verbose", dest="log_verbosity_global", action="count", default=0,
                        help="verbose logs on stderr: -v per-step lines and the retrieval ranking, -vv also "
                             "every candidate and the full prompts (or COPILOT_LOG_LEVEL=INFO|DEBUG)")
    parser.add_argument("--log-file", help="also append the logs to this file (or COPILOT_LOG_FILE)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-env", help="copy .env.example to .env when .env is absent").set_defaults(func=cmd_init_env)

    p = sub.add_parser("check", help="print run mode, .env path, model IDs, API reachability")
    p.add_argument("--no-network", action="store_true", help="skip reachability probes")
    p.set_defaults(func=cmd_check)

    sub.add_parser("seed", help="build the campus DB from data/seed/").set_defaults(func=cmd_seed)

    p = sub.add_parser("ingest", help="run the seven-stage ingestion pipeline over data/sources and data/inbox")
    p.add_argument("--until", choices=["gather", "extract", "clean", "chunk", "embed", "store", "verify"])
    p.add_argument("--store", choices=["sqlite", "sqlite_vec", "chroma", "all"])
    p.add_argument("--resume", metavar="RUN_ID", help="continue a failed run from its last completed stage")
    p.add_argument("--gen-probes", action="store_true", help="ask the chat model for one probe per new document")
    p.add_argument("--show", metavar="STAGE", help="print a stage artifact in readable form")
    p.add_argument("--doc", metavar="SOURCE_ID", help="with --show: one document only")
    p.add_argument("--remove", metavar="SOURCE_ID", help="mark a document removed; the next run deletes its chunks")
    ingest_sub = p.add_subparsers(dest="ingest_action")
    add = ingest_sub.add_parser("add", help="put a PDF or Markdown document in data/inbox/ and record it")
    add.add_argument("file", nargs="?")
    add.add_argument("--url")
    add.add_argument("--licence", required=True)
    add.add_argument("--origin")
    add.add_argument("--title")
    add.add_argument("--language")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("retrieve", help="retrieval only, with scores; --compare prints the Retrieval Lab table")
    p.add_argument("query")
    p.add_argument("--mode", choices=["lexical", "dense", "hybrid", "dense+rerank", "hybrid+rerank", "dense+judge"])
    p.add_argument("--store", choices=["sqlite", "sqlite_vec", "chroma"])
    p.add_argument("-k", type=int)
    p.add_argument("--full", action="store_true", help="print each chunk's full text")
    _log_flags(p)
    p.add_argument("--compare", action="store_true", help="every mode × available store, side by side")
    p.add_argument("--modes", help="with --compare: comma-separated modes")
    p.add_argument("--stores", help="with --compare: comma-separated stores")
    p.set_defaults(func=cmd_retrieve)

    p = sub.add_parser("decide", help="decision playground: every question's answer, distribution, confidence")
    p.add_argument("message")
    p.add_argument("--decider", choices=["jev", "keyword", "llm"], help="default: router.kind from the profile")
    p.add_argument("--account", help="session account (default: app.account_id)")
    p.set_defaults(func=cmd_decide)

    sub.add_parser("jev-smoke", help="send the Jev reference request; print noul, model, usage, latency"
                   ).set_defaults(func=cmd_jev_smoke)

    p = sub.add_parser("ask", help="one turn; prints the answer and a compact trace")
    p.add_argument("message")
    p.add_argument("--thread")
    p.add_argument("--account")
    p.add_argument("--image", help="path to a photographed notice (vision capability)")
    p.add_argument("--yes", action="store_true", help="confirm a pending write")
    p.add_argument("--no", action="store_true", help="cancel a pending write")
    _chunk_flags(p)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("chat", help="interactive session with /thread, /trace, /chunks, /verbose, /profile")
    p.add_argument("--thread")
    p.add_argument("--account")
    _chunk_flags(p)
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("demo", help="run the 14 scripted demo turns and print the scoreboard")
    p.add_argument("--confirm", action="store_true", help="confirm write turns instead of cancelling them")
    _log_flags(p)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("step", help="run the chatbot as it stands after build-path step N")
    p.add_argument("n", type=int, choices=range(1, 13), metavar="N")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="demo scoreboard (default)")
    mode.add_argument("--check", action="store_true", help="the step's checkpoint tests")
    mode.add_argument("--chat", action="store_true", help="a chat session with this step's capabilities")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--thread")
    p.add_argument("--account")
    _chunk_flags(p)
    p.set_defaults(func=cmd_step)

    sub.add_parser("tools", help="list tool specs").set_defaults(func=cmd_tools)

    p = sub.add_parser("eval", help="run the evaluation set; summary per category and per language")
    p.add_argument("--subset", help="category, tag, case ID, or 'routing' (the seed-routing cases); comma-separated")
    p.add_argument("--judges", action="store_true", help="also run the LLM and decision-model faithfulness judges")
    p.add_argument("--vision", action="store_true", help="E14: notice-reader field accuracy per synthetic image")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("trace-report", help="latency and cost summary from runs/traces/")
    p.add_argument("--last", type=int, help="only the last N turns")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_trace_report)

    p = sub.add_parser("ui", help="start the Gradio app on 127.0.0.1")
    p.add_argument("--share", action="store_true", help="also create a public Gradio share link (off by default)")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("mcp-serve", help="start an MCP server over stdio")
    p.add_argument("server", choices=["campus", "public"])
    p.set_defaults(func=cmd_mcp_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass
    args = build_parser().parse_args(argv)
    from .observability import logs

    logs.setup(max(args.log_verbosity_global, getattr(args, "log_verbosity", 0) or 0), args.log_file)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
