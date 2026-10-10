"""Trace parsing: turn many raw session formats into one SessionTrace.

The reflection engine should never have to care whether a session log came from
a JSONL transcript, a plain task_conclusion.md, or a hand-written note list.
This module is the only place that knows about those formats.

Design rule: be permissive and lossy on structure, honest about loss. If we
cannot recover a rationale, we do NOT invent one — we leave it empty and let the
engine mark that dimension as low-confidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import SessionTrace, TraceStep


# --------------------------------------------------------------------------- #
# JSON / JSONL
# --------------------------------------------------------------------------- #


def _step_from_raw(raw: dict[str, Any], index: int) -> TraceStep:
    # Different logs name the same thing differently; normalize here.
    kind = raw.get("kind") or raw.get("type") or raw.get("role") or "note"
    if kind in ("tool", "tool_use", "function_call", "action"):
        kind = "tool_call"
    elif kind in ("tool_result", "function_result", "observation"):
        kind = "tool_result"
    elif kind in ("assistant", "ai", "model"):
        kind = "assistant_message"
    elif kind in ("user", "human"):
        kind = "user_message"

    name = raw.get("name") or raw.get("tool") or raw.get("skill") or ""
    summary = raw.get("summary") or raw.get("content") or raw.get("text") or ""
    if isinstance(summary, (dict, list)):
        summary = json.dumps(summary, ensure_ascii=False)[:500]
    summary = str(summary)

    # rationale/alternatives are the gold we are mining — accept many spellings.
    rationale = raw.get("rationale") or raw.get("reason") or raw.get("why") or ""
    alternatives = raw.get("alternatives") or raw.get("options") or raw.get("considered") or []
    if isinstance(alternatives, str):
        alternatives = [alternatives]

    success = raw.get("success")
    if success is None and "error" in raw and raw["error"]:
        success = False

    return TraceStep(
        index=raw.get("index", index),
        kind=kind,
        name=str(name),
        summary=summary,
        inputs=raw.get("inputs") or raw.get("args") or raw.get("arguments") or {},
        outputs_summary=str(raw.get("outputs_summary") or raw.get("result") or "")[:500],
        rationale=str(rationale),
        alternatives=[str(a) for a in alternatives],
        success=success,
    )


def from_json(data: dict[str, Any]) -> SessionTrace:
    """Parse a single JSON session object."""
    steps = [_step_from_raw(s, i) for i, s in enumerate(data.get("steps", []))]
    return SessionTrace(
        session_id=str(data.get("session_id", "")),
        task_name=str(data.get("task_name", data.get("name", ""))),
        goal=str(data.get("goal", data.get("objective", ""))),
        steps=steps,
        final_outcome=str(data.get("final_outcome", data.get("outcome", ""))),
        source_format="json",
        metadata=data.get("metadata", {}),
    )


def from_jsonl(text: str) -> SessionTrace:
    """Parse JSONL where each line is one step (common agent transcript shape)."""
    steps: list[TraceStep] = []
    meta: dict[str, Any] = {}
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # Not a step line; keep it as a note rather than dropping content.
            steps.append(TraceStep(index=i, kind="note", summary=line[:500]))
            continue
        if obj.get("kind") == "session_meta":
            meta.update(obj)
            continue
        steps.append(_step_from_raw(obj, i))
    return SessionTrace(
        session_id=str(meta.get("session_id", "")),
        task_name=str(meta.get("task_name", "")),
        goal=str(meta.get("goal", "")),
        steps=steps,
        final_outcome=str(meta.get("final_outcome", "")),
        source_format="jsonl",
        metadata=meta,
    )


# --------------------------------------------------------------------------- #
# Markdown (task_conclusion.md style)
# --------------------------------------------------------------------------- #

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_RATIONALE_HINT = re.compile(
    r"(为什么|原因|理由|之所以|因为|为了|避免|而非|而不是|优于|胜在|"
    r"because|reason|rationale|why|chose|chosen|instead of|rather than|so that|in order to)",
    re.IGNORECASE,
)


def from_markdown(text: str) -> SessionTrace:
    """Parse a Markdown conclusion/trace.

    Strategy: headings become the goal/outcome frame, numbered or bulleted
    lines become steps. Lines that *look* like a rationale (containing 为什么 /
    because / 选 / reason ...) are promoted to `rationale`, which is what makes
    them show up as decision points. This is deliberately conservative.
    """
    goal = ""
    outcome = ""
    steps: list[TraceStep] = []
    idx = 0

    for line in text.splitlines():
        h = _HEADING_RE.match(line)
        if h:
            title = h.group(2).strip()
            low = title.lower()
            if not goal and any(k in low for k in ("goal", "objective", "目标", "任务")):
                goal = title
            elif any(k in low for k in ("outcome", "result", "结论", "结果", "小结")):
                outcome = title
            continue

        num = _NUMBERED_RE.match(line)
        bullet = _BULLET_RE.match(line)
        content = None
        if num:
            content = num.group(2).strip()
        elif bullet:
            content = bullet.group(1).strip()

        if content:
            rationale = content if _RATIONALE_HINT.search(content) else ""
            steps.append(
                TraceStep(
                    index=idx,
                    kind="note",
                    summary=content,
                    rationale=rationale,
                )
            )
            idx += 1

    return SessionTrace(
        goal=goal,
        final_outcome=outcome,
        steps=steps,
        source_format="markdown",
    )


# --------------------------------------------------------------------------- #
# Dispatcher + file loading
# --------------------------------------------------------------------------- #


def parse_trace(data: str | dict[str, Any], fmt: str | None = None) -> SessionTrace:
    """Parse a trace from a string or dict, auto-detecting format if needed."""
    if isinstance(data, dict):
        return from_json(data)

    text = data.strip()
    if fmt is None:
        if text.startswith("{"):
            # Could be a JSON object or JSONL. A single well-formed object wins.
            try:
                obj = json.loads(text)
                if isinstance(obj, dict) and "steps" in obj:
                    return from_json(obj)
            except json.JSONDecodeError:
                pass
            return from_jsonl(text)
        elif text.startswith("#") or "\n#" in text or "\n-" in text or "\n*" in text:
            fmt = "markdown"
        else:
            fmt = "jsonl"

    if fmt == "json":
        return from_json(json.loads(text))
    if fmt == "jsonl":
        return from_jsonl(text)
    if fmt == "markdown" or fmt == "md":
        return from_markdown(text)
    raise ValueError(f"Unknown trace format: {fmt!r}")


def load_trace(path: str | Path, fmt: str | None = None) -> SessionTrace:
    """Load and parse a trace file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if fmt is None and p.suffix in (".json",):
        fmt = "json"
    elif fmt is None and p.suffix in (".jsonl", ".ndjson"):
        fmt = "jsonl"
    elif fmt is None and p.suffix in (".md", ".markdown"):
        fmt = "markdown"
    return parse_trace(text, fmt=fmt)


def summarize_trace(trace: SessionTrace) -> dict[str, Any]:
    """Produce the compact, structured digest that gets fed to the reflection.

    This is the function the Agent Skill calls: it must fit in a prompt, so it
    stays small — counts plus the decision points spelled out in full, because
    those are the only steps that carry know-why value.
    """
    return {
        "session_id": trace.session_id,
        "task_name": trace.task_name,
        "goal": trace.goal,
        "final_outcome": trace.final_outcome,
        "n_steps": len(trace.steps),
        "n_tool_calls": len(trace.tool_calls()),
        "n_decision_points": len(trace.decision_points()),
        "n_failures": len(trace.failures()),
        "tool_sequence": [s.name for s in trace.tool_calls() if s.name],
        "decision_points": [
            {
                "index": s.index,
                "name": s.name,
                "what": s.summary,
                "rationale": s.rationale,
                "alternatives": s.alternatives,
            }
            for s in trace.decision_points()
        ],
        "failures": [
            {"index": s.index, "name": s.name, "what": s.summary}
            for s in trace.failures()
        ],
    }
