"""Core data structures for the knowWhy reflection system.

The whole point of knowWhy is to turn the *raw record of what an agent did*
into a *structured explanation of why it did it*. These dataclasses are the
contract between the three layers:

    raw session log --(trace.py)--> SessionTrace --(engine.py)--> Reflection

Keeping the intermediate `SessionTrace` explicit is deliberate. Without it,
reflection silently degrades into generic textbook talk that has nothing to do
with the task the user actually watched happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import json


# --------------------------------------------------------------------------- #
# Trace layer
# --------------------------------------------------------------------------- #


@dataclass
class TraceStep:
    """A single observable action taken during a session.

    A step is intentionally generic. It can be a tool call, an assistant
    message, a user turn, or a free-form note. Everything the reflection engine
    needs to reason about a decision must live in one of these fields.
    """

    index: int
    kind: str  # "tool_call" | "tool_result" | "assistant_message" | "user_message" | "note"
    name: str = ""  # tool / skill name when kind is tool_call
    summary: str = ""  # one-line human readable description
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs_summary: str = ""
    rationale: str = ""  # the agent's own stated reason, if it recorded one
    alternatives: list[str] = field(default_factory=list)  # options considered
    success: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionTrace:
    """Normalized view of one agent session (or a slice of one)."""

    session_id: str = ""
    task_name: str = ""
    goal: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    final_outcome: str = ""
    source_format: str = ""  # how this trace was produced, for debugging
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- convenience ------------------------------------------------------- #

    def decision_points(self) -> list[TraceStep]:
        """Steps that represent a real choice, not just mechanical execution.

        Heuristic: a step is a decision point if the agent recorded a rationale
        OR explicitly listed alternatives. These are exactly the moments worth
        explaining in a know-why reflection.
        """
        return [s for s in self.steps if s.rationale or s.alternatives]

    def tool_calls(self) -> list[TraceStep]:
        return [s for s in self.steps if s.kind == "tool_call"]

    def failures(self) -> list[TraceStep]:
        return [s for s in self.steps if s.success is False]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_name": self.task_name,
            "goal": self.goal,
            "final_outcome": self.final_outcome,
            "source_format": self.source_format,
            "metadata": self.metadata,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionTrace":
        steps = [TraceStep(**s) for s in data.get("steps", [])]
        return cls(
            session_id=data.get("session_id", ""),
            task_name=data.get("task_name", ""),
            goal=data.get("goal", ""),
            steps=steps,
            final_outcome=data.get("final_outcome", ""),
            source_format=data.get("source_format", "dict"),
            metadata=data.get("metadata", {}),
        )


# --------------------------------------------------------------------------- #
# Reflection layer
# --------------------------------------------------------------------------- #

# The five know-why dimensions. Order matters: it mirrors the natural narrative
# of "what were we trying to do -> where did we choose -> why did it work ->
# how do we know -> where else does this apply".
DIMENSIONS = [
    "goal",  # 目标回溯
    "decisions",  # 决策点
    "principles",  # 原理层
    "evidence",  # 证据链
    "transfer",  # 迁移
]

DIMENSION_LABELS_ZH = {
    "goal": "目标回溯",
    "decisions": "决策点",
    "principles": "原理层",
    "evidence": "证据链",
    "transfer": "迁移",
}


@dataclass
class Dimension:
    """One dimension of the reflection, plus a confidence marker.

    `confidence` exists because reflections can themselves hallucinate. Marking
    how sure the explanation is — and where it came from — keeps the tool from
    quietly training the user on invented mechanisms.
    """

    key: str
    title: str
    questions: list[str] = field(default_factory=list)
    answer: str = ""
    confidence: str = "medium"  # "high" | "medium" | "low"
    source: str = ""  # where the claim comes from: trace / domain knowledge / inference

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Reflection:
    """The complete know-why artifact for one trace."""

    trace_summary: str = ""
    dimensions: list[Dimension] = field(default_factory=list)
    learned: list[str] = field(default_factory=list)  # takeaways the user can keep
    stuck: list[str] = field(default_factory=list)  # open questions / gaps
    meta: dict[str, Any] = field(default_factory=dict)

    def dimension(self, key: str) -> Optional[Dimension]:
        for d in self.dimensions:
            if d.key == key:
                return d
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_summary": self.trace_summary,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "learned": self.learned,
            "stuck": self.stuck,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reflection":
        return cls(
            trace_summary=data.get("trace_summary", ""),
            dimensions=[Dimension(**d) for d in data.get("dimensions", [])],
            learned=data.get("learned", []),
            stuck=data.get("stuck", []),
            meta=data.get("meta", {}),
        )

    # -- rendering --------------------------------------------------------- #

    def to_markdown(self) -> str:
        """Render as the Markdown block an agent shows back to the user."""
        lines: list[str] = []
        lines.append("# Know-Why 复盘")
        if self.trace_summary:
            lines.append("")
            lines.append(f"**本次做了什么：** {self.trace_summary}")
        for d in self.dimensions:
            if not d.answer and not d.questions:
                continue
            lines.append("")
            lines.append(f"## {d.title}")
            if d.answer:
                lines.append(d.answer)
            if d.questions:
                lines.append("")
                lines.append("_可以追问：_")
                for q in d.questions:
                    lines.append(f"- {q}")
            if d.source or d.confidence != "medium":
                lines.append("")
                lines.append(f"_(置信度：{d.confidence}；依据：{d.source or '推断'})_")
        if self.learned:
            lines.append("")
            lines.append("## 你这次可以带走的")
            for item in self.learned:
                lines.append(f"- {item}")
        if self.stuck:
            lines.append("")
            lines.append("## 仍待弄清")
            for item in self.stuck:
                lines.append(f"- {item}")
        return "\n".join(lines)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
