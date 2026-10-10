"""Capture adapter: turn a *real* agent run record into a SessionTrace.

Everything else in knowWhy assumes a trace already exists. In practice the hard
part is that nobody hands you one: the agent's real history lives in a runtime's
step log, in a shape that has nothing to do with our `SessionTrace`. This module
is the bridge, and it is why the whole reflection pipeline is usable on actual
work instead of only on hand-written demos.

The primary supported shape is the Mira / sciClaw trace record served by the
local Desktop API (`/api/v1/traces/<id>`), whose `steps` are one of:

  * ``{"role": "assistant", "content": "..."}``                — a narration turn
  * ``{"role": "tool", "tool_name": ..., "tool_input": {...},
      "content": "<json result>", "tool_call_id": ...}``        — one tool call

Key design decisions, each of which matters for reflection quality:

1. **Rationale is NOT invented.** A raw trace records *what* was called and the
   tool's *result*; it almost never records *why*. We therefore leave `rationale`
   empty rather than guessing, and instead surface cheap, honest signals that the
   reflection layer can use: tool failures, retries of the same tool, and the
   assistant's own narration text (which frequently states intent in passing).
2. **Failures are first-class.** The richest know-why material in a real run is
   where it went wrong. We detect failure from the tool result envelope
   (`success: false`, an `error` field, or an SSRF/permission denial) so the
   "证据链" and "仍待弄清" sections have something real to point at.
3. **Errors are parsed out of the result blob, not the call.** Tool results here
   are a JSON string packed into `content`; we parse it leniently and never let
   a malformed blob drop the step.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .models import SessionTrace, TraceStep


# --------------------------------------------------------------------------- #
# Result envelope parsing
# --------------------------------------------------------------------------- #

# Substrings that reliably mean "this call did not do what it was meant to do",
# even when the tool reported success=True (e.g. a sandbox denial returns a
# structured error while the tool wrapper still "succeeded").
_DENIAL_MARKERS = (
    "denied",
    "not permitted",
    "permission",
    "ssrf blocked",
    "blocked ip",
    "not authenticated",
    "unauthorized",
)

# Shell tools whose non-zero exit code is not, by itself, evidence of failure.
_SHELL_TOOLS = ("bash", "shell", "sh", "zsh", "terminal", "run_command")


def _parse_result(content: Any) -> dict[str, Any]:
    """Best-effort parse of a tool result blob into a dict.

    Returns ``{}`` when the content is not a JSON object (e.g. a plain string
    result) — callers must treat an empty dict as "unknown", never as failure.
    """
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {}
    text = content.strip()
    if not text.startswith("{"):
        return {}
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _detect_failure(result: dict[str, Any], raw: str, *, tool_name: str = "") -> tuple[Optional[bool], str]:
    """Return (success, evidence). ``success`` is None when undecidable.

    We only assert False/True when there is real evidence; otherwise None, so a
    reflection never claims a step failed when it merely had an opaque result.

    One subtlety that only shows up on real traces: a shell command frequently
    exits non-zero *on purpose* (grep finding nothing, a CLI signalling "no" via
    exit code, a `test` that legitimately fails). The runtime then stamps
    ``success: false`` even though the command produced exactly the output the
    agent needed. Flagging those as failures floods "仍待弄清" with non-issues,
    so for shell tools we require an actual error signal — not just a non-zero
    exit — before calling it a failure.
    """
    if not result:
        low = raw.lower()
        if any(m in low for m in _DENIAL_MARKERS):
            return False, "结果里出现拒绝/拦截字样"
        return None, ""

    if result.get("success") is False:
        err = result.get("error") or result.get("detail")
        output = result.get("output")
        # Shell tools: non-zero exit with usable output and no error payload is
        # normal control flow, not a failure.
        if tool_name in _SHELL_TOOLS and not err and isinstance(output, str) and output.strip():
            return None, ""
        return False, str(err)[:200] if err else "success=false"
    if result.get("error"):
        return False, str(result["error"])[:200]
    if result.get("success") is True:
        return True, ""
    return None, ""


# Tools that are *themselves* the decision surface: when one appears, the agent
# was explicitly weighing options. We treat these as decision points even without
# a recorded rationale, because their presence is observable evidence of a choice.
_DECISION_TOOLS = ("ask_user", "task_lifecycle")


def _infer_decision_note(step: TraceStep, prev: Optional[TraceStep],
                         tools_seen: set[str]) -> str:
    """Derive a *candidate* decision rationale from observable signals.

    A raw trace records what happened, not why — so we never fabricate a reason.
    Instead we point at the observable fact that makes the step worth asking
    about. The reflection layer pairs this with a probing question, which is
    honest: it says "this step was a choice, here is the evidence, now let's
    figure out the reasoning together".

    The bar for flagging a step is deliberately high: a long agent run has dozens
    of tool calls and flagging all of them buries the real decisions. A bash
    command being run for the 5th time in a row is *not* a decision worth
    reflecting on — but a failure, a pivot, or an explicit question IS.
    """
    reasons: list[str] = []

    # --- strong signals: these alone justify a decision point --------------- #
    if step.success is False:
        reasons.append("这一步失败/被拦，是随后的转向的直接起因")
    if step.name == "ask_user":
        reasons.append("主动向用户发起提问，说明这里存在需要用户裁决的分歧或缺失信息")
    if step.name == "task_lifecycle":
        reasons.append("标记任务边界，是复盘的自然锚点")

    # --- pivot: immediately after a failure, a *different* tool/apparatus --- #
    if prev is not None and prev.success is False and step.name != prev.name:
        reasons.append(f"紧跟在失败的 {prev.name} 之后换用了 {step.name}，是失败后的方案切换")

    # --- retry: the SAME call repeated verbatim, implying dissatisfaction ---- #
    # Only a near-identical repeat is evidence of a retry. Two *different* bash
    # commands back to back are just normal work, not a decision worth surfacing
    # — flagging those would bury the real decisions in a bash-heavy run.
    if prev is not None and _is_near_identical(prev, step):
        reasons.append(f"几乎原样重试了 {step.name}，说明上一次的返回不满足预期")

    # --- first use of a new capability in an already-established flow ------- #
    if step.name and step.name not in tools_seen and len(tools_seen) >= 3:
        reasons.append(f"首次引入 {step.name}，是流程中新增的能力/手段")

    return "；".join(dict.fromkeys(reasons))


def _is_near_identical(a: TraceStep, b: TraceStep) -> bool:
    """True when two calls are the same tool with effectively the same argument.

    We compare a normalized form of the inputs (and fall back to the summary),
    because a genuine retry re-issues the same command; a different command is
    new work, not a retry.
    """
    if not a.name or a.name != b.name:
        return False
    key_a = _call_key(a)
    key_b = _call_key(b)
    return bool(key_a) and key_a == key_b


def _call_key(step: TraceStep) -> str:
    for field in ("command", "url", "query", "path", "file_path"):
        val = step.inputs.get(field)
        if isinstance(val, str):
            return " ".join(val.split())
    return " ".join(step.summary.split())


def _summarize_input(tool_name: str, tool_input: Any) -> str:
    """One-line human description of what the call tried to do.

    This becomes the step's `summary`, i.e. what the user actually sees. Prefer
    the most semantically meaningful field per tool, because "bash" alone tells
    the reader nothing.
    """
    if not isinstance(tool_input, dict):
        return tool_name or "(call)"

    for key in ("command", "url", "query", "name", "path", "file_path", "prompt"):
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            one = " ".join(val.split())
            return f"{tool_name}: {one[:160]}"
    # Fall back to the first scalar field.
    for key, val in tool_input.items():
        if isinstance(val, (str, int, float)) and str(val).strip():
            return f"{tool_name}: {str(val)[:160]}"
    return tool_name or "(call)"


# --------------------------------------------------------------------------- #
# Mira trace ingestion
# --------------------------------------------------------------------------- #


def from_mira_trace(data: dict[str, Any], *, session_id: str = "") -> SessionTrace:
    """Convert one Mira/sciClaw trace record into a SessionTrace.

    ``data`` is the JSON object returned by ``/api/v1/traces/<id>``.
    """
    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError("not a Mira trace record: missing 'steps'")

    steps: list[TraceStep] = []
    tools_seen: set[str] = set()
    idx = 0
    for raw_step in data.get("steps", []):
        role = raw_step.get("role")
        if role == "assistant":
            text = (raw_step.get("content") or "").strip()
            if not text:
                continue
            steps.append(
                TraceStep(
                    index=idx,
                    kind="assistant_message",
                    summary=text[:400],
                )
            )
            idx += 1
        elif role == "tool":
            tool_name = raw_step.get("tool_name") or ""
            tool_input = raw_step.get("tool_input")
            content = raw_step.get("content")
            raw_content = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False
            )
            result = _parse_result(content)
            success, evidence = _detect_failure(result, raw_content, tool_name=tool_name)

            summary = _summarize_input(tool_name, tool_input)
            output_summary = ""
            if result:
                out = result.get("output")
                if isinstance(out, str) and out.strip():
                    output_summary = " ".join(out.split())[:300]
                elif evidence:
                    output_summary = evidence

            step = TraceStep(
                index=idx,
                kind="tool_call",
                name=tool_name,
                summary=summary,
                inputs=tool_input if isinstance(tool_input, dict) else {},
                outputs_summary=output_summary,
                success=success,
            )
            # A raw trace never states *why*, so we attach an observable-evidence
            # note instead of inventing a rationale. This makes the step count as
            # a decision point (i.e. worth explaining), which is the honest call.
            prev = steps[-1] if steps else None
            note = _infer_decision_note(step, prev, tools_seen)
            if note:
                step.rationale = f"[观察到的线索] {note}"
            tools_seen.add(tool_name)
            steps.append(step)
            idx += 1
        # other roles (system, user) are skipped: they carry no decision content

    # Goal / outcome come from the run's overall request + final answer.
    goal = _clean_goal(data.get("request") or "")
    outcome = (data.get("answer") or "").strip()
    skills = data.get("skills_used") or []

    return SessionTrace(
        session_id=session_id or str(data.get("session_id", "")),
        task_name=_task_label(goal),
        goal=goal,
        steps=steps,
        final_outcome=outcome[:600],
        source_format="mira-trace",
        metadata={
            "trace_id": data.get("id"),
            "status": data.get("status"),
            "success": data.get("success"),
            "total_turns": data.get("total_turns"),
            "model": data.get("model"),
            "skills_used": skills,
            "duration_ms": data.get("duration_ms"),
            "executor_name": data.get("executor_name"),
        },
    )


def _task_name_from_goal(goal: str) -> str:
    """A short label for the run — first line, trimmed."""
    if not goal:
        return ""
    first = goal.splitlines()[0].strip()
    return first[:80]


_URL_RE = None  # set lazily to avoid import cost at module load


def _clean_goal(request: str) -> str:
    """Turn a raw run request into a readable goal statement.

    Mira's `request` is the user's literal first message, which often begins with
    a pasted URL or a command dump. Feeding that verbatim into the reflection's
    "目标回溯" dimension produces noise, so we strip leading URLs/whitespace and
    collapse the rest — but we never rewrite or summarize the user's words.
    """
    global _URL_RE
    if _URL_RE is None:
        import re

        _URL_RE = re.compile(r"https?://\S+")
    text = _URL_RE.sub("", request or "").strip()
    # Collapse the leading punctuation/newlines left behind.
    text = text.lstrip(" \t\r\n:：,，。.、-—")
    lines = [" ".join(l.split()) for l in text.splitlines()]
    text = " ".join(l for l in lines if l).strip()
    return text[:400]


def _task_label(goal: str) -> str:
    if not goal:
        return ""
    return goal[:80]


# --------------------------------------------------------------------------- #
# Discovery help (local Desktop API)
# --------------------------------------------------------------------------- #


def mira_trace_list_url(base_url: str, session_id: str) -> str:
    """Endpoint that returns ``{"session_id":..., "trace_ids":[...]}``."""
    return f"{base_url.rstrip('/')}/api/v1/traces/by-session/{session_id}"


def mira_trace_url(base_url: str, trace_id: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/traces/{trace_id}"
