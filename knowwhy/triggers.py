"""Trigger policy: WHEN a know-why reflection should fire.

The user asked for *periodic* reflection, but a fixed wall-clock timer is the
wrong primitive: it fires when nothing interesting happened, and stays silent
right after a hard, instructive task. So knowWhy uses event-anchored triggers
plus a coarse cadence cap.

Three triggers, and they compose:

1. task_boundary  — a task just completed/failed. The single highest-value
   moment, because the goal is still fresh.
2. every_n_turns — a periodic safety net: after N assistant turns without a
   reflection, nudge once. This is the "周期性" requirement, made cheap.
3. manual        — the user typed "讲讲为什么" / "why did you do that" etc.
   Always honored, regardless of counters.

A `TriggerState` object holds the counters; it is trivially serializable so an
agent can persist it in session memory between turns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# Phrases that mean "the user wants a reflection NOW" (manual trigger).
_MANUAL_PATTERNS = [
    r"讲讲为什么",
    r"为什么这么",
    r"为什么这样",
    r"说下原理",
    r"讲一下原理",
    r"复盘",
    r"know[- ]?why",
    r"why did you",
    r"explain your",
    r"walk me through",
    r"怎么想到",
]


@dataclass
class TriggerConfig:
    """Tunable knobs. Defaults are deliberately low-friction."""

    every_n_turns: int = 8  # periodic safety net
    on_task_boundary: bool = True
    on_manual: bool = True
    min_steps_to_reflect: int = 3  # don't waste the user's time on trivial tasks

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TriggerState:
    """Mutable counters an agent carries across turns within a session."""

    turns_since_reflection: int = 0
    reflections_done: int = 0
    last_reflection_turn: int = 0
    snoozed_until_turn: int = 0  # respect "跳过" — do not nag
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TriggerState":
        return cls(**d)


@dataclass
class TriggerDecision:
    fire: bool
    reason: str = ""  # "task_boundary" | "every_n_turns" | "manual" | ""
    message: str = ""  # the low-friction nudge to show the user
    priority: int = 0  # higher wins when several fire at once

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_manual_request(user_text: str) -> bool:
    """Detect an explicit ask for a reflection."""
    low = user_text.strip().lower()
    return any(re.search(p, low) for p in _MANUAL_PATTERNS)


def evaluate(
    *,
    config: TriggerConfig,
    state: TriggerState,
    user_text: str = "",
    task_just_ended: bool = False,
    task_succeeded: Optional[bool] = None,
    current_turn: int = 0,
    n_steps: int = 0,
) -> TriggerDecision:
    """Decide whether to trigger a reflection on this turn.

    Priority when multiple conditions hold: manual > task_boundary > every_n_turns.
    Manual always wins so the user is never told "not now" when they asked.
    """
    if state.snoozed_until_turn and current_turn < state.snoozed_until_turn:
        return TriggerDecision(fire=False, reason="")

    if config.on_manual and user_text and is_manual_request(user_text):
        return TriggerDecision(
            fire=True,
            reason="manual",
            priority=3,
            message="好的，我把刚才的流程拆开讲一下为什么。",
        )

    if task_just_ended and config.on_task_boundary:
        if n_steps >= config.min_steps_to_reflect:
            verdict = "完成" if task_succeeded is None else ("成功" if task_succeeded else "未完成")
            return TriggerDecision(
                fire=True,
                reason="task_boundary",
                priority=2,
                message=(
                    f"任务{verdict}了。花两分钟复盘一下这套流程，"
                    f"下次你自己也能走一遍 —— 要展开看哪一步？还是先跳过？"
                ),
            )
        return TriggerDecision(fire=False, reason="")

    if config.every_n_turns and state.turns_since_reflection >= config.every_n_turns:
        return TriggerDecision(
            fire=True,
            reason="every_n_turns",
            priority=1,
            message=(
                f"我们已经连续推进了 {state.turns_since_reflection} 轮，"
                f"要不要抽 1 分钟对刚才这段做个 know-why 复盘？不想的话回「跳过」。"
            ),
        )

    return TriggerDecision(fire=False, reason="")


def advance(state: TriggerState, fired: bool, current_turn: int = 0) -> TriggerState:
    """Update counters after a turn. Call this exactly once per turn."""
    state.turns_since_reflection += 1
    if fired:
        state.turns_since_reflection = 0
        state.reflections_done += 1
        state.last_reflection_turn = current_turn
    return state


def snooze(state: TriggerState, turns: int = 8, current_turn: int = 0) -> TriggerState:
    """Honor a '跳过' from the user — silence the periodic trigger for a while."""
    state.snoozed_until_turn = current_turn + turns
    state.turns_since_reflection = 0
    return state
