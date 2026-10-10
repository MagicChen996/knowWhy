"""Tests for the annotations mechanism (knowwhy/annotations.py + report merge).

The whole point of annotations is that the delivered report is *filled in*, not a
page of open questions. These tests lock that contract: annotations override the
scaffold, survive a round-trip to disk, and never silently lose the library's own
trace-derived facts.

Run with: pytest -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowwhy.annotations import (
    Annotations,
    StepAnnotation,
    dump_annotations,
    load_annotations,
    scaffold_annotations,
)
from knowwhy.models import SessionTrace, TraceStep
from knowwhy.report import render_report_html, write_report

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
REAL_ANNOTATIONS = EXAMPLES / "reports" / "mira_session.annotations.json"


def _trace() -> SessionTrace:
    return SessionTrace(
        session_id="s1",
        task_name="t",
        steps=[
            TraceStep(index=0, kind="tool_call", name="web_fetch", summary="抓页面",
                      rationale="[观察到的线索] 失败后转向"),
            TraceStep(index=1, kind="tool_call", name="bash", summary="curl 重试"),
            TraceStep(index=2, kind="assistant_message", summary="我看到了"),
        ],
    )


# --------------------------------------------------------------------------- #
# data model
# --------------------------------------------------------------------------- #


def test_step_annotation_is_empty_only_when_no_content():
    assert StepAnnotation().is_empty()
    assert not StepAnnotation(why="x").is_empty()
    assert not StepAnnotation(principle="y").is_empty()
    assert not StepAnnotation(alternatives=["a"]).is_empty()


def test_annotation_roundtrip_preserves_fields():
    a = StepAnnotation(why="w", principle="p", alternatives=["a", "b"],
                       sources=["s"], confidence="high")
    b = StepAnnotation.from_dict(json.loads(json.dumps(a.to_dict())))
    assert b.why == "w" and b.principle == "p"
    assert b.alternatives == ["a", "b"] and b.sources == ["s"]
    assert b.confidence == "high"


def test_annotation_accepts_scalar_for_list_fields():
    a = StepAnnotation.from_dict({"why": "w", "sources": "single", "alternatives": "one"})
    assert a.sources == ["single"] and a.alternatives == ["one"]


def test_annotations_keys_are_ints():
    ann = Annotations.from_dict({"steps": {"3": {"why": "w"}, "bad": {}}})
    assert 3 in ann.steps
    assert len(ann) == 1  # the malformed key is dropped, not crashed on


def test_annotations_roundtrip_file(tmp_path):
    ann = Annotations(session_id="s", steps={0: StepAnnotation(why="w")})
    p = dump_annotations(ann, tmp_path / "a.json")
    back = load_annotations(p)
    assert back.session_id == "s"
    assert back.get(0).why == "w"


def test_filled_count():
    ann = Annotations(steps={0: StepAnnotation(why="w"), 1: StepAnnotation(), 2: StepAnnotation(principle="p")})
    assert ann.filled_count() == 2


# --------------------------------------------------------------------------- #
# scaffolding
# --------------------------------------------------------------------------- #


def test_scaffold_keys_only_tool_steps():
    ann = scaffold_annotations(_trace())
    assert set(ann.steps) == {0, 1}  # assistant message excluded
    assert all(a.is_empty() for a in ann.steps.values())


# --------------------------------------------------------------------------- #
# merge into the report — the contract that matters
# --------------------------------------------------------------------------- #


def test_unannotated_report_shows_placeholders():
    html = render_report_html(_trace(), None)
    assert 'class="pill todo"' in html
    assert "待补全" in html
    assert 'class="explained"' not in html


def test_annotated_report_replaces_placeholder_with_explanation():
    ann = Annotations(steps={0: StepAnnotation(
        why="因为官方页没有开放接口", principle="SSRF 防护会拒绝内网地址",
        sources=["OWASP SSRF"], confidence="high",
    )})
    html = render_report_html(_trace(), None, annotations=ann)
    assert 'class="explained"' in html
    assert "SSRF 防护会拒绝内网地址" in html
    assert "OWASP SSRF" in html
    assert "为什么这么做" in html
    assert "因为官方页没有开放接口" in html


def test_annotation_why_overrides_inferred_note():
    """An agent's real explanation must beat the trace-inferred '线索'."""
    ann = Annotations(steps={0: StepAnnotation(why="真实解释")})
    html = render_report_html(_trace(), None, annotations=ann)
    assert "真实解释" in html
    # the inferred marker for step 0 is gone (front matter may still mention it)
    assert "观察到的线索] 失败后转向" not in html


def test_annotation_only_covers_its_own_step():
    ann = Annotations(steps={0: StepAnnotation(principle="P0")})
    html = render_report_html(_trace(), None, annotations=ann)
    # step 1 (bash) still shows a placeholder; the footer legend also uses the
    # pill but is not a slot, so scope the count to the timeline body.
    body = html.split("<footer>")[0]
    assert body.count('class="pill todo"') == 1
    assert body.count('class="explained"') == 1


def test_write_report_accepts_annotations(tmp_path):
    ann = Annotations(steps={0: StepAnnotation(principle="P")})
    out = write_report(_trace(), None, tmp_path / "r.html", annotations=ann)
    assert "P" in out.read_text(encoding="utf-8")


def test_coverage_chip_shows_when_annotations_present():
    ann = Annotations(steps={0: StepAnnotation(principle="p")})
    html = render_report_html(_trace(), None, annotations=ann)
    assert "已解释" in html


# --------------------------------------------------------------------------- #
# the shipped example is genuinely filled in
# --------------------------------------------------------------------------- #


def test_shipped_example_annotations_cover_all_tool_steps():
    assert REAL_ANNOTATIONS.exists()
    ann = load_annotations(REAL_ANNOTATIONS)
    from knowwhy.capture import load_any_trace

    trace = load_any_trace(EXAMPLES / "real" / "mira_trace_raw.json")
    tool_idx = {s.index for s in trace.tool_calls()}
    missing = tool_idx - set(ann.steps)
    assert not missing, f"unexplained tool steps: {sorted(missing)}"


def test_shipped_report_is_filled_not_placeholder():
    """The committed HTML must not ship with empty principle slots."""
    report = EXAMPLES / "reports" / "reflection_report.html"
    html = report.read_text(encoding="utf-8")
    assert html.count('class="explained"') >= 20
    # only the footer legend should reference the TODO state
    assert html.count('class="pill todo"') <= 1
