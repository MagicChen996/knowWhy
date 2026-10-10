"""Tests for the capture adapter (knowwhy/capture.py).

These exercise the real-world path: a runtime's own trace record → SessionTrace.
The fixtures below are trimmed but faithful copies of the shape returned by the
Mira local API (`/api/v1/traces/<id>`), which is what the adapter targets.

Run with: pytest -q
"""

from __future__ import annotations

import json

import pytest

from knowwhy import from_mira_trace
from knowwhy.capture import (
    _clean_goal,
    _detect_failure,
    _is_near_identical,
    mira_trace_list_url,
    mira_trace_url,
)
from knowwhy.models import TraceStep


def _trace(*steps, request="做点事", answer="做完了"):
    return {"id": "t1", "session_id": "s1", "request": request, "answer": answer, "steps": list(steps)}


def _tool(name, result, tool_input=None):
    return {
        "role": "tool",
        "tool_name": name,
        "tool_input": tool_input or {},
        "content": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
    }


def _assistant(text):
    return {"role": "assistant", "content": text}


# --------------------------------------------------------------------------- #
# basic conversion
# --------------------------------------------------------------------------- #


def test_assistant_turns_and_tool_calls_are_both_kept():
    t = from_mira_trace(_trace(
        _assistant("我先看看环境"),
        _tool("bash", {"success": True, "output": "ok"}, {"command": "ls"}),
    ))
    assert [s.kind for s in t.steps] == ["assistant_message", "tool_call"]
    assert t.tool_calls()[0].name == "bash"


def test_empty_assistant_turns_are_dropped():
    t = from_mira_trace(_trace(_assistant("   "), _tool("bash", {"success": True})))
    assert len(t.steps) == 1


def test_goal_strips_leading_url():
    """The real request often starts with a pasted URL; the goal must read clean."""
    t = from_mira_trace(_trace(
        _tool("bash", {"success": True}),
        request="http://127.0.0.1:62621/share/sessions/abc 帮我把它同步过来",
    ))
    assert not t.goal.startswith("http")
    assert "同步" in t.goal


def test_metadata_carries_run_facts():
    d = _trace(_tool("bash", {"success": True}))
    d.update(status="completed", total_turns=12, model="m", skills_used=["skill-creator"])
    t = from_mira_trace(d)
    assert t.metadata["status"] == "completed"
    assert t.metadata["skills_used"] == ["skill-creator"]
    assert t.source_format == "mira-trace"


def test_rejects_non_trace_input():
    with pytest.raises(ValueError):
        from_mira_trace({"foo": "bar"})


# --------------------------------------------------------------------------- #
# failure detection — the crux of reflection quality
# --------------------------------------------------------------------------- #


def test_success_false_with_error_is_failure():
    ok, ev = _detect_failure({"success": False, "error": "boom"}, "{}", tool_name="bash")
    assert ok is False and "boom" in ev


def test_shell_nonzero_exit_with_output_is_not_a_failure():
    """A shell command can exit non-zero on purpose while doing its job."""
    ok, _ = _detect_failure(
        {"success": False, "output": "found 3 files", "error": None},
        "{}",
        tool_name="bash",
    )
    assert ok is None


def test_shell_nonzero_exit_with_empty_output_is_failure():
    ok, _ = _detect_failure(
        {"success": False, "output": "", "error": None}, "{}", tool_name="bash"
    )
    assert ok is False


def test_ssrf_denial_detected_from_raw_text():
    ok, ev = _detect_failure({}, "SSRF blocked: blocked IP 127.0.0.1", tool_name="web_fetch")
    assert ok is False


def test_opaque_result_is_undecided_not_failure():
    assert _detect_failure({}, "just a plain string result")[0] is None


def test_end_to_end_trace_marks_only_real_failures():
    t = from_mira_trace(_trace(
        _tool("web_fetch", {"error": "SSRF blocked: blocked IP 127.0.0.1", "success": False}),
        _tool("bash", {"success": False, "output": "usable", "error": None}),  # not a failure
        _tool("bash", {"success": False, "output": "", "error": "Traceback..."}),  # failure
    ))
    fails = t.failures()
    assert len(fails) == 2
    assert fails[0].name == "web_fetch"
    assert fails[1].name == "bash"


# --------------------------------------------------------------------------- #
# decision-point inference (observable evidence, never invented rationale)
# --------------------------------------------------------------------------- #


def test_failure_creates_a_decision_point():
    t = from_mira_trace(_trace(
        _tool("web_fetch", {"success": False, "error": "SSRF blocked"}),
    ))
    dps = t.decision_points()
    assert len(dps) == 1
    assert "观察到的线索" in dps[0].rationale


def test_pivot_after_failure_is_flagged():
    t = from_mira_trace(_trace(
        _tool("web_fetch", {"success": False, "error": "SSRF blocked"}),
        _tool("bash", {"success": True, "output": "ok"}, {"command": "curl ..."}),
    ))
    bash_step = t.tool_calls()[1]
    assert "方案切换" in bash_step.rationale


def test_ordinary_different_bash_commands_are_not_flagged():
    """Signal-to-noise: a run of different bash commands is work, not decisions."""
    t = from_mira_trace(_trace(
        _tool("bash", {"success": True, "output": "a"}, {"command": "ls"}),
        _tool("bash", {"success": True, "output": "b"}, {"command": "pwd"}),
        _tool("bash", {"success": True, "output": "c"}, {"command": "whoami"}),
    ))
    assert t.decision_points() == []


def test_verbatim_retry_is_flagged():
    same = {"command": "python -m pytest"}
    t = from_mira_trace(_trace(
        _tool("bash", {"success": True, "output": "x"}, same),
        _tool("bash", {"success": True, "output": "y"}, same),
    ))
    assert "原样重试" in t.tool_calls()[1].rationale


def test_near_identical_requires_same_tool():
    a = TraceStep(index=0, kind="tool_call", name="bash", inputs={"command": "ls"})
    b = TraceStep(index=1, kind="tool_call", name="grep", inputs={"command": "ls"})
    assert not _is_near_identical(a, b)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def test_clean_goal_collapses_and_trims():
    assert _clean_goal("http://x/y   再来  做这件事\n\n  继续") == "再来 做这件事 继续"
    assert _clean_goal("") == ""


def test_url_builders():
    assert mira_trace_list_url("http://127.0.0.1:1/", "s") == "http://127.0.0.1:1/api/v1/traces/by-session/s"
    assert mira_trace_url("http://127.0.0.1:1", "t") == "http://127.0.0.1:1/api/v1/traces/t"
