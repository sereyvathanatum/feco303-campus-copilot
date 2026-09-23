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
