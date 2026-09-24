"""Core data types shared by every Clev component.

Keep these stable: observers, deciders, executors and the tracer all speak in these types.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

ActionKind = Literal["click", "type", "key", "scroll", "back", "wait", "done", "fail"]
DecidedBy = Literal["jev", "llm", "mock"]


class Element(BaseModel):
    id: str  # stable within one observation
    role: str  # button, link, textbox, menuitem, checkbox...
    name: str  # accessible name / label
    value: str | None = None
    context: str = ""  # short path of ancestor names, e.g. "Compose > Toolbar"
    enabled: bool = True
    focused: bool = False
    visible: bool = True
    bounds: tuple[int, int, int, int] | None = None  # x, y, width, height


class Observation(BaseModel):
    app: str  # "chromium", "Mail", ...
    title: str  # window / page title
    url: str | None = None
    elements: list[Element] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

    def element(self, element_id: str) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)


class Action(BaseModel):
    kind: ActionKind
    element_id: str | None = None
    text: str | None = None  # filled by planner for "type"
    key: str | None = None  # e.g. "cmd+enter"
    direction: Literal["up", "down"] | None = None


class Option(BaseModel):
    """One numbered choice presented to the decider.

    `label` is what the decider sees and returns (e.g. "1", "SUBGOAL_DONE"); `action` is
    what executing that choice means. Global options like NONE_OF_THESE / STUCK have no action.
    """

    label: str
    line: str  # rendered text shown to the decider
    action: Action | None = None


class SerializedState(BaseModel):
    """Compact decider-ready rendering of an Observation (built by clev/state in Phase 3)."""

    text: str
    options: list[Option]
    token_estimate: int = 0

    def option(self, label: str) -> Option | None:
        return next((o for o in self.options if o.label == label), None)


class Decision(BaseModel):
    action: Action
    confidence: float  # probability of the chosen option
    probs: dict[str, float] = Field(default_factory=dict)  # option label -> probability
    decided_by: DecidedBy
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    chosen_label: str | None = None


class StepRecord(BaseModel):
    """One control-loop step, written as a single JSONL line by the tracer."""

    run_id: str
    step: int
    subgoal: str
    observation: Observation
    state_text: str | None = None
    decision: Decision | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    # Jev check questions: subgoal_complete, error_visible, progress
    checks: dict[str, float] = Field(default_factory=dict)
    executed: bool = False
    blocked_by_safety: str | None = None
    error: str | None = None
    timestamp: float = Field(default_factory=time.time)
