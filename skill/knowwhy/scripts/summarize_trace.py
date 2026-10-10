#!/usr/bin/env python3
"""summarize_trace.py — bundle script for the knowWhy Skill.

The Skill needs one cheap, dependency-free way to turn whatever trace the agent
recorded into the compact digest that seeds a know-why reflection, AND to build
the 5-dimension scaffold. This wraps the `knowwhy` library so the Skill works
even if the user has not pip-installed it (it falls back to a vendored import
path next to this file).

Usage:
    python summarize_trace.py summarize <trace>            # JSON digest
    python summarize_trace.py reflect   <trace> [--focus KEY] [--json]
    python summarize_trace.py review    [--store PATH]
    python summarize_trace.py trigger   --user-text "..." --task-ended --n-steps 6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from a checkout without installation: look for the `knowwhy`
# package in the repo root (two levels up from skill/knowwhy/scripts/).
_here = Path(__file__).resolve()
for candidate in (_here.parents[3], _here.parents[2]):
    if (candidate / "knowwhy" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from knowwhy import (
        build_reflection,
        from_mira_trace,
        load_any_trace,
        load_trace,
        parse_trace,
        summarize_trace,
        write_report,
    )
    from knowwhy.recall import (
        DEFAULT_STORE,
        GrowthEntry,
        append_entry,
        grow_review,
    )
    from knowwhy.triggers import TriggerConfig, TriggerState, advance, evaluate
except ImportError:
    sys.stderr.write(
        "ERROR: could not import the `knowwhy` package.\n"
        "Install it (`pip install .` from the repo root) or run this script "
        "from inside the knowWhy repository.\n"
    )
    raise SystemExit(2)


def _load(path: str):
    if path == "-":
        return parse_trace(sys.stdin.read())
    return load_trace(path)


def _load_any(path: str):
    """Load a trace, auto-detecting raw runtime dumps (e.g. Mira records)."""
    if path == "-":
        return parse_trace(sys.stdin.read())
    return load_any_trace(path)


def main() -> int:
    p = argparse.ArgumentParser(description="knowWhy Skill helper")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summarize")
    s.add_argument("trace")
    s.set_defaults(cmd="summarize")

    c = sub.add_parser("capture")
    c.add_argument("input", help="a runtime trace record (e.g. Mira /api/v1/traces/<id> dump)")
    c.add_argument("-o", "--out", default=None)
    c.set_defaults(cmd="capture")

    rp = sub.add_parser("report")
    rp.add_argument("trace")
    rp.add_argument("-o", "--out", default=None)
    rp.add_argument("--no-open", action="store_true")
    rp.set_defaults(cmd="report")

    r = sub.add_parser("reflect")
    r.add_argument("trace")
    r.add_argument("--focus", default=None)
    r.add_argument("--json", action="store_true")
    r.add_argument("--record", action="store_true",
                   help="append the reflection's learned/stuck to the growth store")
    r.add_argument("--store", default=DEFAULT_STORE, help="growth store path")
    r.set_defaults(cmd="reflect")

    v = sub.add_parser("review")
    v.add_argument("--store", default=DEFAULT_STORE)
    v.set_defaults(cmd="review")

    t = sub.add_parser("trigger")
    t.add_argument("--state", default=None)
    t.add_argument("--user-text", default="")
    t.add_argument("--task-ended", action="store_true")
    t.add_argument("--turn", type=int, default=0)
    t.add_argument("--n-steps", type=int, default=0)
    t.add_argument("--every-n", type=int, default=8)
    t.set_defaults(cmd="trigger")

    args = p.parse_args()

    if args.cmd == "summarize":
        print(json.dumps(summarize_trace(_load(args.trace)), ensure_ascii=False, indent=2))
    elif args.cmd == "capture":
        trace = from_mira_trace(json.loads(Path(args.input).read_text(encoding="utf-8")))
        payload = trace.to_dict()
        if args.out:
            Path(args.out).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"wrote {args.out} ({len(trace.steps)} steps)")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "reflect":
        trace = _load(args.trace)
        ref = build_reflection(trace, focus=args.focus)
        if args.record:
            entry = GrowthEntry.from_reflection(
                ref, session_id=trace.session_id, task_name=trace.task_name
            )
            append_entry(entry, store=args.store)
        print(ref.to_json() if args.json else ref.to_markdown())
    elif args.cmd == "report":
        import webbrowser
        trace = _load_any(args.trace)
        out = args.out or (args.trace + ".report.html")
        path = write_report(trace, build_reflection(trace), out)
        print(f"wrote {path}  ({len(trace.steps)} steps)")
        if not args.no_open:
            try:
                webbrowser.open(Path(path).resolve().as_uri())
                print("已用默认浏览器打开")
            except Exception:
                pass
    elif args.cmd == "review":
        print(grow_review(store=args.store))
    elif args.cmd == "trigger":
        state = TriggerState()
        if args.state and Path(args.state).exists():
            state = TriggerState.from_dict(json.loads(Path(args.state).read_text(encoding="utf-8")))
        d = evaluate(
            config=TriggerConfig(every_n_turns=args.every_n),
            state=state,
            user_text=args.user_text,
            task_just_ended=args.task_ended,
            current_turn=args.turn,
            n_steps=args.n_steps,
        )
        advance(state, d.fire, current_turn=args.turn)
        if args.state:
            Path(args.state).write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(d.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
