"""Tests for the knowwhy library. Run with: pytest -q"""

import json
from pathlib import Path

import pytest

from knowwhy import (
    DIMENSIONS,
    Reflection,
    SessionTrace,
    TraceStep,
    build_reflection,
    from_jsonl,
    from_markdown,
    is_manual_request,
    parse_trace,
    summarize_trace,
)
from knowwhy.triggers import TriggerConfig, TriggerState, advance, evaluate, snooze
from knowwhy.recall import GrowthEntry, append_entry, grow_review, load_entries

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# --------------------------------------------------------------------------- #
# trace parsing
# --------------------------------------------------------------------------- #


def test_parse_jsonl_extracts_decisions():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    assert trace.task_name == "预测某分子溶解度"
    assert len(trace.tool_calls()) == 4
    dps = trace.decision_points()
    # steps with rationale OR alternatives
    assert len(dps) >= 4
    assert any(s.name == "chem-properties" for s in dps)


def test_parse_jsonl_detects_failure():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    assert len(trace.failures()) == 1
    assert trace.failures()[0].name == "reactify"


def test_parse_markdown_promotes_rationale_lines():
    trace = from_markdown((EXAMPLES / "demo_conclusion.md").read_text(encoding="utf-8"))
    assert trace.goal
    # lines containing 因为/选择/而非 should be promoted to rationale
    assert len(trace.decision_points()) >= 2


def test_parse_trace_autodetects_jsonl():
    text = (EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8")
    trace = parse_trace(text)
    assert trace.source_format == "jsonl"


def test_parse_trace_autodetects_markdown():
    text = (EXAMPLES / "demo_conclusion.md").read_text(encoding="utf-8")
    trace = parse_trace(text)
    assert trace.source_format == "markdown"


def test_parse_trace_rejects_unknown_format():
    with pytest.raises(ValueError):
        parse_trace("{}", fmt="xml")


def test_session_trace_roundtrip():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    clone = SessionTrace.from_dict(trace.to_dict())
    assert clone.task_name == trace.task_name
    assert len(clone.steps) == len(trace.steps)


# --------------------------------------------------------------------------- #
# summarize
# --------------------------------------------------------------------------- #


def test_summarize_shape():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    s = summarize_trace(trace)
    assert s["n_tool_calls"] == 4
    assert "chem-properties" in s["tool_sequence"]
    assert s["n_failures"] == 1
    # decision points carry rationale through
    assert any(d["rationale"] for d in s["decision_points"])


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #


def test_build_reflection_has_all_dimensions_in_order():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    r = build_reflection(trace)
    assert [d.key for d in r.dimensions] == DIMENSIONS


def test_reflection_focus_narrows():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    r = build_reflection(trace, focus="decisions")
    assert len(r.dimensions) == 1
    assert r.dimensions[0].key == "decisions"


def test_principles_dimension_is_flagged_low_confidence():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    r = build_reflection(trace)
    assert r.dimension("principles").confidence == "low"


def test_reflection_markdown_and_json_render():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    r = build_reflection(trace)
    md = r.to_markdown()
    assert "Know-Why 复盘" in md
    assert "决策点" in md
    data = json.loads(r.to_json())
    assert len(data["dimensions"]) == 5


def test_reflection_roundtrip():
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    r = build_reflection(trace)
    clone = Reflection.from_dict(r.to_dict())
    assert clone.trace_summary == r.trace_summary


# --------------------------------------------------------------------------- #
# triggers
# --------------------------------------------------------------------------- #


def test_manual_detection():
    assert is_manual_request("讲讲为什么你这么做")
    assert is_manual_request("why did you use that tool")
    assert is_manual_request("帮我复盘一下")
    assert not is_manual_request("继续下一步")


def test_manual_trigger_wins_and_has_top_priority():
    cfg = TriggerConfig()
    state = TriggerState(turns_since_reflection=100)
    d = evaluate(config=cfg, state=state, user_text="讲讲为什么", current_turn=5)
    assert d.fire and d.reason == "manual" and d.priority == 3


def test_task_boundary_triggers_when_enough_steps():
    cfg = TriggerConfig()
    state = TriggerState()
    d = evaluate(config=cfg, state=state, task_just_ended=True, task_succeeded=True,
                 n_steps=5, current_turn=1)
    assert d.fire and d.reason == "task_boundary"


def test_task_boundary_skips_trivial_task():
    cfg = TriggerConfig()
    state = TriggerState()
    d = evaluate(config=cfg, state=state, task_just_ended=True, n_steps=1)
    assert not d.fire


def test_every_n_turns_fires_on_cadence():
    cfg = TriggerConfig(every_n_turns=3)
    state = TriggerState(turns_since_reflection=3)
    d = evaluate(config=cfg, state=state, current_turn=3)
    assert d.fire and d.reason == "every_n_turns"


def test_advance_resets_counter_on_fire():
    state = TriggerState(turns_since_reflection=5)
    advance(state, fired=True, current_turn=7)
    assert state.turns_since_reflection == 0
    assert state.reflections_done == 1
    assert state.last_reflection_turn == 7


def test_snooze_silences_periodic():
    cfg = TriggerConfig(every_n_turns=3)
    state = TriggerState(turns_since_reflection=10)
    snooze(state, turns=8, current_turn=2)
    d = evaluate(config=cfg, state=state, current_turn=4)
    assert not d.fire


# --------------------------------------------------------------------------- #
# recall
# --------------------------------------------------------------------------- #


def test_growth_store_roundtrip(tmp_path):
    store = tmp_path / "growth.jsonl"
    trace = from_jsonl((EXAMPLES / "demo_session.jsonl").read_text(encoding="utf-8"))
    r = build_reflection(trace)
    append_entry(GrowthEntry.from_reflection(r, session_id=trace.session_id), store=store)
    entries = load_entries(store)
    assert len(entries) == 1


def test_growth_review_empty(tmp_path):
    review = grow_review(store=tmp_path / "none.jsonl")
    assert "还没有记录" in review


def test_growth_review_aggregates(tmp_path):
    store = tmp_path / "growth.jsonl"
    append_entry(GrowthEntry(timestamp="t1", learned=["a", "b"], stuck=["x"]), store=store)
    append_entry(GrowthEntry(timestamp="t2", learned=["b", "c"], stuck=["y"]), store=store)
    review = grow_review(store=store)
    assert "你已经搞懂的" in review
    # dedupe keeps 'b' once
    assert review.count("- b") == 1
