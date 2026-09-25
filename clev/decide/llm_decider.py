"""LLM decider: picks one option label with a structured-output call.

Used as the LLM-only baseline and (Phase 5) as the escalation path when Jev is unsure. It sees
exactly the same serialized state and options as Jev, so comparisons isolate the decider.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, create_model

from clev.core.interfaces import LLMClient
from clev.core.types import Decision, SerializedState, StepRecord
from clev.planner.prompts import DECIDE_SYSTEM
from clev.state.serialize import history_lines


class _YesNo(BaseModel):
    answer: bool


def choice_schema(labels: list[str]) -> type[BaseModel]:
    """A schema whose `choice` can only be one of the option labels."""
    return create_model(
        "NextAction",
        reason=(str, Field(description="One short sentence: why this option")),
        choice=(Literal[tuple(labels)], ...),
    )


def decision_prompt(state: SerializedState, history: list[StepRecord]) -> str:
    recent = history_lines(history) or ["(none yet)"]
    return state.text + "\n\nRECENT ACTIONS:\n" + "\n".join(recent)


class LLMDecider:
    def __init__(self, llm: LLMClient, model: str):
        self.llm = llm
        self.model = model

    async def decide(
        self, state: SerializedState, subgoal: str, history: list[StepRecord]
    ) -> Decision:
        labels = [o.label for o in state.options]
        result = await self.llm.complete(
            model=self.model,
            system=DECIDE_SYSTEM,
            user=decision_prompt(state, history),
            schema=choice_schema(labels),
            max_output_tokens=400,
        )
        label = result.parsed.choice
        option = state.option(label)
        return Decision(
            action=option.action.model_copy() if option and option.action else None,
            confidence=1.0,  # no calibrated probability from a single structured call
            probs={label: 1.0},
            decided_by="llm",
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
            chosen_label=label,
        )

    async def check(self, state: SerializedState, question: str) -> float:
        result = await self.llm.complete(
            model=self.model,
            system="Answer the question about the screen with true or false.",
            user=f"{state.text}\n\nQUESTION: {question}",
            schema=_YesNo,
            max_output_tokens=200,
        )
        return 1.0 if result.parsed.answer else 0.0
