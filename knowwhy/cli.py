"""knowwhy CLI.

Three subcommands that map 1:1 onto the three layers:

    knowwhy summarize <trace>          -> the compact digest (fed to an agent)
    knowwhy reflect   <trace> [--focus decisions]  -> the 5-dim scaffold (md/json)
    knowwhy review    [--store path]   -> the periodic growth review

Plus `knowwhy trigger` for the trigger policy, so an agent can ask "should I
reflect now?" without reimplementing the counters.

Design goal: every subcommand is a pure function of files + flags, so it can be
shelled out to from any agent runtime (this is the "function" half of the
deliverable; the Skill is the "when/how to call it" half).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .engine import build_reflection
from .models import DIMENSIONS
from .recall import DEFAULT_STORE, append_entry, grow_review, load_entries, GrowthEntry
from .trace import load_trace, parse_trace, summarize_trace
from .triggers import TriggerConfig, TriggerState, advance, evaluate, is_manual_request


def _read_trace(path: str, fmt: str | None):
    if path == "-":
        return parse_trace(sys.stdin.read(), fmt=fmt)
    return load_trace(path, fmt=fmt)


def cmd_summarize(args: argparse.Namespace) -> int:
    trace = _read_trace(args.trace, args.format)
    print(json.dumps(summarize_trace(trace), ensure_ascii=False, indent=2))
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    trace = _read_trace(args.trace, args.format)
    reflection = build_reflection(trace, focus=args.focus)

    if args.record:
        entry = GrowthEntry.from_reflection(
            reflection, session_id=trace.session_id, task_name=trace.task_name
        )
        append_entry(entry, store=args.store)

    if args.json:
        print(reflection.to_json())
    else:
        print(reflection.to_markdown())
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    print(grow_review(store=args.store, last_n=args.last))
    return 0


def cmd_trigger(args: argparse.Namespace) -> int:
    """Evaluate the trigger policy once and print the decision as JSON.

    State is passed in/out via --state (a JSON file) so an agent can carry the
    counters across turns without a server.
    """
    cfg = TriggerConfig(every_n_turns=args.every_n)
    state = TriggerState()
    if args.state and Path(args.state).exists():
        state = TriggerState.from_dict(json.loads(Path(args.state).read_text(encoding="utf-8")))

    decision = evaluate(
        config=cfg,
        state=state,
        user_text=args.user_text or "",
        task_just_ended=args.task_ended,
        current_turn=args.turn,
        n_steps=args.n_steps,
    )
    advance(state, decision.fire, current_turn=args.turn)

    if args.state:
        Path(args.state).write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_check_manual(args: argparse.Namespace) -> int:
    """Exit 0 if the text is a manual know-why request, else 1. Handy in shells."""
    hit = is_manual_request(args.text)
    print("manual" if hit else "not_manual")
    return 0 if hit else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="knowwhy",
        description="Turn an agent's session trace into a structured know-why reflection.",
    )
    p.add_argument("--version", action="version", version=f"knowwhy {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summarize", help="produce the compact trace digest")
    s.add_argument("trace", help="trace file path, or - for stdin")
    s.add_argument("--format", choices=["json", "jsonl", "markdown"], default=None)
    s.set_defaults(func=cmd_summarize)

    r = sub.add_parser("reflect", help="build the 5-dimension reflection scaffold")
    r.add_argument("trace", help="trace file path, or - for stdin")
    r.add_argument("--format", choices=["json", "jsonl", "markdown"], default=None)
    r.add_argument("--focus", choices=DIMENSIONS, default=None,
                   help="narrow to one dimension (the '展开哪一条' interaction)")
    r.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    r.add_argument("--record", action="store_true", help="also append to the growth store")
    r.add_argument("--store", default=DEFAULT_STORE, help="growth store path")
    r.set_defaults(func=cmd_reflect)

    rev = sub.add_parser("review", help="periodic growth review")
    rev.add_argument("--store", default=DEFAULT_STORE)
    rev.add_argument("--last", type=int, default=10)
    rev.set_defaults(func=cmd_review)

    t = sub.add_parser("trigger", help="evaluate the reflection trigger policy")
    t.add_argument("--state", default=None, help="JSON file holding TriggerState")
    t.add_argument("--user-text", default="")
    t.add_argument("--task-ended", action="store_true")
    t.add_argument("--turn", type=int, default=0)
    t.add_argument("--n-steps", type=int, default=0)
    t.add_argument("--every-n", type=int, default=8)
    t.set_defaults(func=cmd_trigger)

    m = sub.add_parser("check-manual", help="is this text a manual know-why request?")
    m.add_argument("text")
    m.set_defaults(func=cmd_check_manual)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
