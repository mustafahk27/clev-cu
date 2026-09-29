"""Escalation policy (plan §9): Jev decides; the LLM takes over steps where Jev is unsure.

Every escalation and every Jev-triggered replan carries a reason, so escalation rate and causes
can be measured from traces.
"""

from __future__ import annotations

from dataclasses import dataclass

from clev.core.errors import ClevError
from clev.core.interfaces import Decider
from clev.core.types import Decision, Element, SerializedState, StepRecord
from clev.decide.questions import ERROR_VISIBLE, PROGRESS, SUBGOAL_COMPLETE

CONTROL_ESCALATE = {"NONE_OF_THESE", "STUCK"}
NO_PROGRESS = 0.5  # progress probability below this counts as "flat or negative"
NO_PROGRESS_STEPS = 3
REPEAT_STEPS = 3


@dataclass(frozen=True)
class Policy:
    confidence_threshold: float = 0.6
    margin: float = 0.1
    done_threshold: float = 0.7
    error_threshold: float = 0.7


def _executed_steps(history: list[StepRecord], subgoal: str) -> list[StepRecord]:
    return [r for r in history if r.event == "step" and r.subgoal == subgoal and r.executed]


def _signature(d: Decision | None, target: Element | None) -> tuple | None:
    """What was done to what, by role and name (ids change between observations)."""
    if d is None or d.action is None:
        return None
    a = d.action
    who = (target.role, target.name) if target else None
    return (a.kind, who, a.key, a.direction)


def _history_signature(r: StepRecord) -> tuple | None:
    a = r.decision.action if r.decision else None
    target = r.observation.element(a.element_id) if a and a.element_id and r.observation else None
    return _signature(r.decision, target)


def escalation_reason(
    jev: Decision, state: SerializedState, subgoal: str, history: list[StepRecord], policy: Policy
) -> str | None:
    """Why this Jev decision should go to the LLM instead, or None to accept it."""
    if jev.chosen_label in CONTROL_ESCALATE:
        return f"jev chose {jev.chosen_label}"
    if jev.confidence < policy.confidence_threshold:
        return f"low confidence {jev.confidence:.2f} < {policy.confidence_threshold}"
    top = sorted(jev.probs.values(), reverse=True)
    if len(top) >= 2 and top[0] - top[1] < policy.margin:
        return f"top two options within {top[0] - top[1]:.2f} < margin {policy.margin}"

    done = _executed_steps(history, subgoal)
    recent = [r.decision.checks.get(PROGRESS) for r in done[-NO_PROGRESS_STEPS:] if r.decision]
    if (
        len(recent) == NO_PROGRESS_STEPS
        and all(p is not None for p in recent)
        and all(p < NO_PROGRESS for p in recent)
    ):
        return f"no progress for {NO_PROGRESS_STEPS} steps"

    last = [_history_signature(r) for r in done[-(REPEAT_STEPS - 1) :]]
    sig = _signature(jev, state.elements.get(jev.chosen_label or ""))
    if sig is not None and len(last) == REPEAT_STEPS - 1 and all(s == sig for s in last):
        return f"same action {REPEAT_STEPS} times in a row"
    return None


def _control(label: str, base: Decision, reason: str) -> Decision:
    """Turn a Jev decision into a loop control signal (SUBGOAL_DONE / STUCK)."""
    return base.model_copy(
        update={"action": None, "chosen_label": label, "escalation_reason": reason}
    )


class EscalatingDecider:
    """Decider: Jev first; the fallback (LLM) decides when the policy says Jev is unsure."""

    def __init__(self, primary: Decider, fallback: Decider, policy: Policy | None = None):
        self.primary = primary
        self.fallback = fallback
        self.policy = policy or Policy()

    async def decide(
        self, state: SerializedState, subgoal: str, history: list[StepRecord]
    ) -> Decision:
        try:
            jev = await self.primary.decide(state, subgoal, history)
        except ClevError as e:  # Jev down after retries: this step goes to the LLM
            return await self._escalate(state, subgoal, history, None, f"jev error: {e}")

        # Screen-level checks first: they're cheaper than acting on the wrong screen.
        if jev.checks.get(ERROR_VISIBLE, 0.0) > self.policy.error_threshold:
            return _control("STUCK", jev, f"error visible ({jev.checks[ERROR_VISIBLE]:.2f})")
        if jev.checks.get(SUBGOAL_COMPLETE, 0.0) > self.policy.done_threshold:
            return _control(
                "SUBGOAL_DONE", jev, f"subgoal complete ({jev.checks[SUBGOAL_COMPLETE]:.2f})"
            )
        # Plan §9: two escalations in a row without progress -> replan.
        steps = [r for r in history if r.event == "step" and r.decision]
        if (
            len(steps) >= 2
            and all(r.decision.escalated for r in steps[-2:])
            and jev.checks.get(PROGRESS, 1.0) < NO_PROGRESS
        ):
            return _control("STUCK", jev, "2 escalations in a row without progress")

        reason = escalation_reason(jev, state, subgoal, history, self.policy)
        if reason is None:
            return jev
        return await self._escalate(state, subgoal, history, jev, reason)

    async def _escalate(
        self,
        state: SerializedState,
        subgoal: str,
        history: list[StepRecord],
        jev: Decision | None,
        reason: str,
    ) -> Decision:
        llm = await self.fallback.decide(state, subgoal, history)
        update = {"escalated": True, "escalation_reason": reason}
        if jev is not None:
            update |= {
                "checks": jev.checks,
                "primary_choice": jev.chosen_label,
                "primary_confidence": jev.confidence,
                "primary_probs": jev.probs,
                "latency_ms": jev.latency_ms + llm.latency_ms,
                "cost_usd": jev.cost_usd + llm.cost_usd,
            }
        return llm.model_copy(update=update)

    async def check(self, state: SerializedState, question: str) -> float:
        return await self.primary.check(state, question)
