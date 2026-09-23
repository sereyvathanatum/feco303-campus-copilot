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


# ----------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="campus_copilot.cli", description="CamTech Campus Copilot")
    parser.add_argument("--profile", help="profile name in profiles/ (default: COPILOT_PROFILE or baseline)")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE",
                        help="override one profile key, for example --set rag.top_k=6")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
