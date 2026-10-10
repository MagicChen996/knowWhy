"""Annotations: the agent's half of the reflection.

The library can prove *what* happened (the trace) and it can scaffold *what to
ask* (the reflection), but it cannot know the domain — so every per-step
"为什么 / 原理 / 知识点" slot starts empty. This module is how those slots get
filled: an agent (or a person) writes a structured annotation file, and the
renderer merges it back into the report.

Why a separate file instead of editing the HTML?

  * The report is a *build product*. If you edit it directly, regenerating it
    (new trace, new format, a bug fix) silently throws your work away.
  * Annotations must survive re-rendering, be diffable in git, and be
    reviewable on their own.
  * It forces the explanation to be *addressed to a specific step*, which is
    what keeps a reflection honest — no free-floating textbook prose.

Annotation file format (JSON)::

    {
      "session_id": "pcbprwe0",
      "steps": {
        "3": {
          "why": "官方分享页没有开放 API，直接抓页面只能拿到前端外壳……",
          "principle": "SSRF 防护：服务端在发起请求前会解析目标地址并拒绝内网 IP……",
          "sources": ["本项目 capture.py 的 _DENIAL_MARKERS 逻辑"],
          "confidence": "high"
        }
      }
    }

Keys are the step **index** (as shown in the report, 0-based; the UI displays
index+1). `why` fills the "为什么这么做" slot, `principle` the "原理 / 知识点"
slot. `sources` / `confidence` are optional but encouraged — a claim without a
source is exactly the kind of thing this project exists to avoid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class StepAnnotation:
    """What an agent learned/explained about one step."""

    why: str = ""
    principle: str = ""
    alternatives: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: str = ""  # "high" | "medium" | "low" | ""

    def is_empty(self) -> bool:
        return not (self.why or self.principle or self.alternatives)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.why:
            d["why"] = self.why
        if self.principle:
            d["principle"] = self.principle
        if self.alternatives:
            d["alternatives"] = list(self.alternatives)
        if self.sources:
            d["sources"] = list(self.sources)
        if self.confidence:
            d["confidence"] = self.confidence
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StepAnnotation":
        alts = d.get("alternatives") or []
        if isinstance(alts, str):
            alts = [alts]
        srcs = d.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        return cls(
            why=str(d.get("why", "") or ""),
            principle=str(d.get("principle", "") or ""),
            alternatives=[str(a) for a in alts],
            sources=[str(s) for s in srcs],
            confidence=str(d.get("confidence", "") or ""),
        )


@dataclass
class Annotations:
    """A whole annotation set for one session, keyed by step index."""

    session_id: str = ""
    steps: dict[int, StepAnnotation] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def get(self, index: int) -> Optional[StepAnnotation]:
        return self.steps.get(index)

    def __len__(self) -> int:
        return len(self.steps)

    def filled_count(self) -> int:
        return sum(1 for a in self.steps.values() if not a.is_empty())

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "steps": {str(k): v.to_dict() for k, v in sorted(self.steps.items())},
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Annotations":
        raw_steps = d.get("steps", {}) or {}
        steps: dict[int, StepAnnotation] = {}
        for k, v in raw_steps.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            steps[idx] = StepAnnotation.from_dict(v if isinstance(v, dict) else {})
        return cls(
            session_id=str(d.get("session_id", "") or ""),
            steps=steps,
            meta=d.get("meta", {}) or {},
        )


def load_annotations(path: str | Path) -> Annotations:
    """Read an annotation JSON file."""
    text = Path(path).read_text(encoding="utf-8")
    return Annotations.from_dict(json.loads(text))


def dump_annotations(ann: Annotations, path: str | Path) -> Path:
    """Write an annotation set back to JSON (stable, diffable)."""
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(ann.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def scaffold_annotations(
    trace: Any, *, reflection: Any = None
) -> Annotations:
    """Produce a blank annotation file pre-keyed to every tool step.

    This is the file an agent is expected to fill in. Pre-seeding the keys (and
    echoing each step's summary as a comment-like hint) is what makes the filling
    step mechanical rather than a blank-page problem.
    """
    steps: dict[int, StepAnnotation] = {}
    for s in getattr(trace, "steps", []):
        if s.kind != "tool_call":
            continue
        steps[s.index] = StepAnnotation()
    return Annotations(
        session_id=getattr(trace, "session_id", ""),
        steps=steps,
        meta={
            "task_name": getattr(trace, "task_name", ""),
            "hint": "为每个步骤填写 why（为什么这么做）与 principle（原理/知识点）。"
                    "留空表示库保持其骨架占位。",
        },
    )
