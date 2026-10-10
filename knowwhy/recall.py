"""Growth memory: make reflection cumulative across sessions.

A reflection that evaporates after one turn does not build capability. This
module persists what the user learned and what they got stuck on into a small
JSONL log, and can surface it later ("上次你搞懂了 X，这次遇到的是它的近亲"),
plus a periodic review digest.

Kept deliberately simple: append-only JSONL, one record per reflection. No DB
dependency, so the package installs anywhere and the file is human-readable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Reflection


DEFAULT_STORE = ".knowwhy/growth.jsonl"


@dataclass
class GrowthEntry:
    timestamp: str
    session_id: str = ""
    task_name: str = ""
    learned: list[str] = field(default_factory=list)
    stuck: list[str] = field(default_factory=list)
    n_decision_points: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_reflection(cls, r: Reflection, session_id: str = "", task_name: str = "") -> "GrowthEntry":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            task_name=task_name or r.meta.get("task_name", ""),
            learned=list(r.learned),
            stuck=list(r.stuck),
            n_decision_points=len(
                [d for d in r.dimensions if d.key == "decisions" and d.answer and "（轨迹里没有" not in d.answer]
            ),
        )


def append_entry(entry: GrowthEntry, store: str | Path = DEFAULT_STORE) -> Path:
    """Append one growth entry to the JSONL store."""
    p = Path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    return p


def load_entries(store: str | Path = DEFAULT_STORE) -> list[GrowthEntry]:
    p = Path(store)
    if not p.exists():
        return []
    out: list[GrowthEntry] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(GrowthEntry(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def grow_review(store: str | Path = DEFAULT_STORE, last_n: int = 10) -> str:
    """Render a periodic 'what have you learned' review.

    This is what a scheduled task / weekly check-in shows the user: the visible
    curve of capability growth, plus unresolved gaps worth revisiting.
    """
    entries = load_entries(store)[-last_n:]
    if not entries:
        return "# 认知成长回顾\n\n还没有记录。完成几次 know-why 复盘后这里会累积你的学习轨迹。"

    lines = ["# 认知成长回顾", ""]
    lines.append(f"共 {len(entries)} 次复盘记录（最近 {len(entries)} 次）。")
    lines.append("")

    all_learned: list[str] = []
    all_stuck: list[str] = []
    for e in entries:
        all_learned.extend(e.learned)
        all_stuck.extend(e.stuck)

    if all_learned:
        lines.append("## 你已经搞懂的")
        for item in dict.fromkeys(all_learned):  # dedupe, keep order
            lines.append(f"- {item}")
        lines.append("")

    if all_stuck:
        lines.append("## 还卡着的（建议下次优先攻克）")
        for item in dict.fromkeys(all_stuck):
            lines.append(f"- {item}")

    return "\n".join(lines)
