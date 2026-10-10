"""Tests for the HTML report renderer (knowwhy/report.py).

The report is the user-facing deliverable, so these tests focus on the things
that silently break it: self-containment (no network), correct escaping, the
"why / principle" slots being present but honestly marked, and the
auto-detection of raw runtime traces (which otherwise yields an empty report).

Run with: pytest -q
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from knowwhy import build_reflection, from_mira_trace
from knowwhy.capture import load_any_trace, looks_like_mira_trace
from knowwhy.models import SessionTrace, TraceStep
from knowwhy.report import render_report_html, write_report

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _trace() -> SessionTrace:
    return SessionTrace(
        session_id="s1",
        task_name="测试任务",
        goal="验证报告渲染",
        final_outcome="完成",
        source_format="test",
        metadata={"model": "m", "total_turns": 3},
        steps=[
            TraceStep(index=0, kind="assistant_message", summary="我先看看"),
            TraceStep(
                index=1, kind="tool_call", name="grep",
                summary="grep: foo", inputs={"command": "grep foo"},
                outputs_summary="3 matches", success=True,
                rationale="[观察到的线索] 这一步失败/被拦",
            ),
            TraceStep(
                index=2, kind="tool_call", name="curl",
                summary="curl: http://x", inputs={"url": "http://x"},
                outputs_summary="SSRF blocked", success=False,
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# self-containment & escaping
# --------------------------------------------------------------------------- #


def test_report_is_standalone_no_network():
    html = render_report_html(_trace(), build_reflection(_trace()))
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', html), "must not load remote assets"
    assert "<!DOCTYPE html>" in html
    assert "<style>" in html  # CSS inlined


def test_report_escapes_user_content():
    """A trace summary containing HTML must not break out of its element."""
    t = SessionTrace(task_name="<script>alert(1)</script>", steps=[
        TraceStep(index=0, kind="tool_call", name="x",
                  summary='<img src=x onerror=alert(1)>', inputs={})
    ])
    html = render_report_html(t, None)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    # the raw injection payload must not survive as live markup
    assert "<img src=x onerror" not in html


def test_report_handles_empty_trace():
    html = render_report_html(SessionTrace(), None)
    assert "<!DOCTYPE html>" in html
    # no timeline entries were fabricated
    assert "<details" not in html
    assert 'class="step"' not in html


# --------------------------------------------------------------------------- #
# the core learning surface: timeline + why + principle scaffold
# --------------------------------------------------------------------------- #


def test_timeline_renders_one_card_per_step():
    t = _trace()
    html = render_report_html(t, build_reflection(t))
    assert html.count("<details") == len(t.steps)


def test_each_card_has_the_principle_scaffold():
    t = _trace()
    html = render_report_html(t, build_reflection(t))
    # every tool call offers the principle slot, explicitly marked as TODO
    assert html.count("原理 / 知识点") == len(t.tool_calls())
    assert 'class="pill todo"' in html


def test_inferred_why_is_marked_as_inference():
    t = _trace()
    html = render_report_html(t, build_reflection(t))
    assert "为什么这么做" in html
    assert 'class="pill infer"' in html
    # the evidence line must be visible to the reader
    assert "观察到的线索" in html


def test_agent_recorded_why_is_marked_as_fact():
    t = SessionTrace(steps=[
        TraceStep(index=0, kind="tool_call", name="t", summary="s",
                  rationale="因为数据放不进显存，所以换小批量", inputs={})
    ])
    html = render_report_html(t, None)
    assert 'class="pill fact"' in html
    assert "agent 记录" in html


def test_failed_step_is_visually_flagged():
    t = _trace()
    html = render_report_html(t, build_reflection(t))
    assert 'data-status="fail"' in html
    assert "失败 / 被拦" in html


def test_metadata_chips_present():
    html = render_report_html(_trace(), None)
    assert "工具调用" in html and "决策点" in html


# --------------------------------------------------------------------------- #
# write_report + auto-detection
# --------------------------------------------------------------------------- #


def test_write_report_creates_file(tmp_path):
    out = write_report(_trace(), None, tmp_path / "sub" / "r.html")
    assert out.exists() and out.suffix == ".html"
    assert "<!DOCTYPE html>" in out.read_text(encoding="utf-8")


def test_looks_like_mira_trace_detects_real_record():
    data = json.loads((EXAMPLES / "real" / "mira_trace_raw.json").read_text(encoding="utf-8"))
    assert looks_like_mira_trace(data)


def test_looks_like_mira_trace_rejects_generic_trace():
    assert not looks_like_mira_trace({"steps": [{"kind": "tool_call", "name": "x"}]})
    assert not looks_like_mira_trace({})
    assert not looks_like_mira_trace("not a dict")


def test_load_any_trace_auto_detects_mira_and_keeps_signals():
    """Regression: a raw Mira dump must not be parsed as generic JSON, which
    silently zeroes out decisions/failures and empties the report."""
    t = load_any_trace(EXAMPLES / "real" / "mira_trace_raw.json")
    assert t.source_format == "mira-trace"
    assert len(t.decision_points()) > 0
    assert len(t.failures()) > 0


def test_load_any_trace_still_reads_generic_jsonl():
    t = load_any_trace(EXAMPLES / "demo_session.jsonl")
    assert t.source_format == "jsonl"
    assert len(t.tool_calls()) == 4


def test_real_trace_report_has_nonzero_stats():
    t = load_any_trace(EXAMPLES / "real" / "mira_trace_raw.json")
    html = render_report_html(t, build_reflection(t))
    m = re.search(r'<div class="n">(\d+)</div><div class="k">决策点', html)
    assert m and int(m.group(1)) > 0
