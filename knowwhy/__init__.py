"""knowWhy — turn an agent's session trace into a structured know-why reflection.

Public API (the contract the Skill and the CLI both rely on)::

    from knowwhy import load_trace, parse_trace, summarize_trace, build_reflection

Layering, kept deliberately explicit:

    raw session log --(trace.py)--> SessionTrace --(engine.py)--> Reflection
                                          |
                    triggers.py (when) · recall.py (across sessions)

Nothing here is domain-specific: the library owns *how to compute* the reflection
scaffold, the Skill owns *when to trigger it and how to explain it to a person*.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .engine import DIMENSION_QUESTIONS, build_reflection
from .models import (
    DIMENSION_LABELS_ZH,
    DIMENSIONS,
    Dimension,
    Reflection,
    SessionTrace,
    TraceStep,
)
from .recall import (
    DEFAULT_STORE,
    GrowthEntry,
    append_entry,
    grow_review,
    load_entries,
)
from .trace import (
    from_json,
    from_jsonl,
    from_markdown,
    load_trace,
    parse_trace,
    summarize_trace,
)
from .triggers import (
    TriggerConfig,
    TriggerDecision,
    TriggerState,
    advance,
    evaluate,
    is_manual_request,
    snooze,
)

__all__ = [
    "__version__",
    # models
    "DIMENSIONS",
    "DIMENSION_LABELS_ZH",
    "Dimension",
    "Reflection",
    "SessionTrace",
    "TraceStep",
    # trace
    "from_json",
    "from_jsonl",
    "from_markdown",
    "load_trace",
    "parse_trace",
    "summarize_trace",
    # engine
    "build_reflection",
    "DIMENSION_QUESTIONS",
    # triggers
    "TriggerConfig",
    "TriggerDecision",
    "TriggerState",
    "evaluate",
    "advance",
    "snooze",
    "is_manual_request",
    # recall
    "DEFAULT_STORE",
    "GrowthEntry",
    "append_entry",
    "load_entries",
    "grow_review",
]
