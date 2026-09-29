"""Core data types shared by every Clev component.

Keep these stable: observers, deciders, executors and the tracer all speak in these types.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

ActionKind = Literal["click", "type", "key", "scroll", "back", "wait", "goto", "done", "fail"]
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
    bounds: tuple[int, int, int, int] | None = None  # x, y, width, height (page coordinates)
    editable: bool = False  # accepts typed text (text inputs, editable comboboxes, contenteditable)


class Observation(BaseModel):
    app: str  # "chromium", "Mail", ...
    title: str  # window / page title
    url: str | None = None
    elements: list[Element] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)
    viewport: tuple[int, int, int, int] | None = None  # visible area: scroll x, y, width, height

    def element(self, element_id: str) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)


class Action(BaseModel):
    kind: ActionKind
    element_id: str | None = None
    text: str | None = None  # filled by planner for "type"
    key: str | None = None  # e.g. "cmd+enter"
    direction: Literal["up", "down"] | None = None
    url: str | None = None  # for "goto": only the planner's start URL, never a decider choice


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
    elements: dict[str, Element] = Field(default_factory=dict)  # option label -> element
    header: str = ""  # the text above OPTIONS: page, goal, done so far, context

    def option(self, label: str) -> Option | None:
        return next((o for o in self.options if o.label == label), None)


class Decision(BaseModel):
    action: Action | None  # None for control choices: SUBGOAL_DONE, NONE_OF_THESE, STUCK
    confidence: float  # probability of the chosen option
    probs: dict[str, float] = Field(default_factory=dict)  # option label -> probability
    decided_by: DecidedBy
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    chosen_label: str | None = None
    # Jev's yes/no checks for this screen: subgoal_complete, error_visible, progress.
    checks: dict[str, float] = Field(default_factory=dict)
    escalated: bool = False
    escalation_reason: str | None = None
    # Jev's own answer, kept when a step is escalated (needed for calibration in Phase 6).
    primary_choice: str | None = None
    primary_confidence: float | None = None
    primary_probs: dict[str, float] = Field(default_factory=dict)


class Plan(BaseModel):
    """Planner output: where to start and the ordered subgoals."""

    start_url: str | None = None
    subgoals: list[str]


class StepRecord(BaseModel):
    """One trace line: a control-loop step, or a run event (plan, replan, end)."""

    run_id: str
    step: int
    subgoal: str
    event: Literal["plan", "step", "replan", "end"] = "step"
    # Traces keep only the elements that became options (plus the chosen one), not the whole page.
    observation: Observation | None = None
    state_text: str | None = None
    decision: Decision | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    # Jev check questions: subgoal_complete, error_visible, progress
    checks: dict[str, float] = Field(default_factory=dict)
    executed: bool = False
    blocked_by_safety: str | None = None
    error: str | None = None
    subgoals: list[str] | None = None  # plan / replan events
    note: str | None = None  # e.g. replan reason, end result
    cost_usd: float = 0.0  # all model calls made in this step (decider, planner, write_text)
    latency_ms: float = 0.0  # whole step, observe to executed
    timestamp: float = Field(default_factory=time.time)
