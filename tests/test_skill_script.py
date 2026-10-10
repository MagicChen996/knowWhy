"""Tests for the bundled Skill script (skill/knowwhy/scripts/summarize_trace.py).

The Skill script is the agent-facing entry point, and it must stay runnable even
when the `knowwhy` package is NOT pip-installed — that fallback (finding the repo
package upward from the script) is exactly what breaks silently. These tests keep
the Skill's own CLI contract honest, independent of the library tests.

Run with: pytest -q
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "knowwhy" / "scripts" / "summarize_trace.py"
DEMO_JSONL = REPO / "examples" / "demo_session.jsonl"
DEMO_MD = REPO / "examples" / "demo_conclusion.md"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )


def test_script_exists_and_runs_uninstalled():
    assert SCRIPT.exists()
    r = _run("summarize", str(DEMO_JSONL))
    assert r.returncode == 0, r.stderr
    digest = json.loads(r.stdout)
    assert digest["task_name"] == "预测某分子溶解度"
    assert digest["n_decision_points"] >= 4


def test_skill_script_summarize_matches_library():
    r = _run("summarize", str(DEMO_JSONL))
    from knowwhy import summarize_trace, load_trace

    assert json.loads(r.stdout) == summarize_trace(load_trace(DEMO_JSONL))


def test_skill_script_reflect_markdown_focus():
    r = _run("reflect", str(DEMO_MD), "--focus", "decisions", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert [d["key"] for d in payload["dimensions"]] == ["decisions"]


def test_skill_script_record_persists_growth(tmp_path):
    """Regression: the Skill's `reflect` must support --record/--store so the
    cumulative-growth promise in SKILL.md actually works from the Skill path."""
    store = tmp_path / "growth.jsonl"
    r = _run("reflect", str(DEMO_JSONL), "--record", "--store", str(store))
    assert r.returncode == 0, r.stderr
    assert store.exists()
    lines = [l for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["learned"]

    # review reflects it back
    r2 = _run("review", "--store", str(store))
    assert r2.returncode == 0, r2.stderr
    assert "认知成长回顾" in r2.stdout


def test_skill_script_trigger_persists_state(tmp_path):
    state = tmp_path / "state.json"
    r = _run(
        "trigger", "--state", str(state),
        "--task-ended", "--n-steps", "6", "--turn", "6",
    )
    assert r.returncode == 0, r.stderr
    decision = json.loads(r.stdout)
    assert decision["fire"] is True
    assert decision["reason"] == "task_boundary"
    assert state.exists()
    assert json.loads(state.read_text(encoding="utf-8"))["reflections_done"] == 1
