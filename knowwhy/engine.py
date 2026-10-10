"""The 5-dimension know-why reflection engine.

This module builds a *scaffold* reflection from a trace. It is deliberately not
a text generator: an LLM (the agent using the Skill) fills the prose. What the
engine guarantees is:

  * the right five dimensions, in the right order, with the right question set;
  * per-dimension confidence + provenance, so the agent doesn't present
    speculation as fact;
  * a `learned` / `stuck` pair that makes growth cumulative across sessions.

Why scaffold-first instead of "just ask the LLM to explain"? Because an
unstructured prompt drifts into textbook generalities ("DFT is accurate because
...") that have nothing to do with the task the user actually watched. Anchoring
each dimension to concrete trace evidence is what keeps the reflection honest.
"""

from __future__ import annotations

from typing import Optional

from .models import DIMENSIONS, DIMENSION_LABELS_ZH, Dimension, Reflection, SessionTrace


# --------------------------------------------------------------------------- #
# Question templates (generic — no domain assumption)
# --------------------------------------------------------------------------- #

DIMENSION_QUESTIONS: dict[str, list[str]] = {
    "goal": [
        "这个任务真正要解决的问题是什么？",
        "为什么目标是这个，而不是看起来更显然的另一个？",
        "成功/失败的判据是什么？谁来判定？",
    ],
    "decisions": [
        "在整个流程里，哪几步是真正的「选择」而不是机械执行？",
        "每个选择当时依据了什么信息？如果是你，缺了哪些信息就做不出这个选择？",
        "有哪些被放弃的备选方案？为什么被放弃？",
    ],
    "principles": [
        "每一步背后起作用的机制/公式/领域知识是什么？",
        "为什么这样做会有效？它的适用前提是什么？",
        "什么情况下这套做法会失效（反例）？",
    ],
    "evidence": [
        "结论是从哪些数据/文献/中间结果推出来的？",
        "哪一步是「观察到的事实」，哪一步是「推断」？",
        "最弱的一环在哪里？如果有反证会从哪来？",
    ],
    "transfer": [
        "如果换一个不同的问题，这套思路里哪部分还能复用？",
        "这次踩的坑/走的捷径，下次应该原样照搬还是改掉？",
        "要独立完成同类任务，你还需要补上哪块能力？",
    ],
}


def _goal_dimension(trace: SessionTrace) -> Dimension:
    answer = ""
    conf = "medium"
    if trace.goal:
        answer = f"目标：{trace.goal}"
        if trace.final_outcome:
            answer += f"\n结果：{trace.final_outcome}"
        conf = "high"
    else:
        conf = "low"
    return Dimension(
        key="goal",
        title=DIMENSION_LABELS_ZH["goal"],
        questions=DIMENSION_QUESTIONS["goal"],
        answer=answer,
        confidence=conf,
        source="trace" if trace.goal else "",
    )


def _decisions_dimension(trace: SessionTrace) -> Dimension:
    dps = trace.decision_points()
    lines: list[str] = []
    conf = "high" if dps else "low"
    for s in dps:
        label = s.name or f"step {s.index}"
        line = f"- **{label}**：{s.summary}"
        if s.rationale:
            line += f"\n  依据：{s.rationale}"
        if s.alternatives:
            line += f"\n  考虑过的替代：{', '.join(s.alternatives)}"
        lines.append(line)
    answer = "\n".join(lines) if lines else "（轨迹里没有记录明确的决策点与理由，这一维需要追问或回看。）"
    return Dimension(
        key="decisions",
        title=DIMENSION_LABELS_ZH["decisions"],
        questions=DIMENSION_QUESTIONS["decisions"],
        answer=answer,
        confidence=conf,
        source="trace" if dps else "",
    )


def _principles_dimension(trace: SessionTrace) -> Dimension:
    # The engine cannot know the mechanism by itself; it flags where the agent
    # must supply domain reasoning and marks confidence honestly.
    tools = sorted({s.name for s in trace.tool_calls() if s.name})
    hint = ""
    if tools:
        hint = f"涉及的工具/方法：{', '.join(tools)}。需逐一说明其作用机理与适用前提。"
    return Dimension(
        key="principles",
        title=DIMENSION_LABELS_ZH["principles"],
        questions=DIMENSION_QUESTIONS["principles"],
        answer=hint + ("\n（由 agent 结合领域知识补全；标注置信度与来源。）" if hint else ""),
        confidence="low",  # needs external knowledge -> flag for the agent
        source="domain knowledge (to be supplied)",
    )


def _evidence_dimension(trace: SessionTrace) -> Dimension:
    fails = trace.failures()
    lines: list[str] = []
    if trace.final_outcome:
        lines.append(f"- 结论：{trace.final_outcome}")
    if fails:
        lines.append(f"- 过程中有 {len(fails)} 处失败/回退，是重要的证据节点：")
        for s in fails:
            lines.append(f"  - step {s.index} {s.name or ''}：{s.summary}")
    lines.append("- 待 agent 标注：哪一步是事实、哪一步是推断。")
    return Dimension(
        key="evidence",
        title=DIMENSION_LABELS_ZH["evidence"],
        questions=DIMENSION_QUESTIONS["evidence"],
        answer="\n".join(lines),
        confidence="medium",
        source="trace",
    )


def _transfer_dimension(trace: SessionTrace) -> Dimension:
    return Dimension(
        key="transfer",
        title=DIMENSION_LABELS_ZH["transfer"],
        questions=DIMENSION_QUESTIONS["transfer"],
        answer="（由 agent 给出 1-3 条可迁移的普适经验，并说明适用边界。）",
        confidence="low",
        source="inference (to be supplied)",
    )


_DIMENSION_BUILDERS = {
    "goal": _goal_dimension,
    "decisions": _decisions_dimension,
    "principles": _principles_dimension,
    "evidence": _evidence_dimension,
    "transfer": _transfer_dimension,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def build_reflection(trace: SessionTrace, focus: Optional[str] = None) -> Reflection:
    """Build the 5-dimension scaffold for a trace.

    `focus` optionally narrows to one dimension key ("decisions", "principles",
    ...) for the "展开哪一条" interaction — the scaffold then only contains that
    dimension, but `learned`/`stuck` are still emitted.
    """
    keys = [focus] if focus in DIMENSIONS else DIMENSIONS
    dims = [_DIMENSION_BUILDERS[k](trace) for k in keys]

    summary_bits = []
    if trace.task_name:
        summary_bits.append(trace.task_name)
    if trace.goal:
        summary_bits.append(f"目标：{trace.goal}")
    summary_bits.append(f"{len(trace.steps)} 步、{len(trace.tool_calls())} 次工具调用")
    if trace.decision_points():
        summary_bits.append(f"{len(trace.decision_points())} 个决策点")
    trace_summary = "；".join(summary_bits)

    # learned / stuck are seed hints; the agent finalizes them.
    learned = []
    for s in trace.decision_points():
        if s.rationale:
            learned.append(f"决策「{s.name or s.index}」的依据：{s.rationale}")
    stuck = []
    if not trace.decision_points():
        stuck.append("本次轨迹没有记录决策理由，建议在关键选择处显式记下 rationale。")
    for s in trace.failures():
        stuck.append(f"step {s.index} {s.name or ''} 曾失败，值得弄清根因。")

    return Reflection(
        trace_summary=trace_summary,
        dimensions=dims,
        learned=learned,
        stuck=stuck,
        meta={
            "source_format": trace.source_format,
            "focus": focus,
            "n_steps": len(trace.steps),
            "dimensions": keys,
        },
    )
