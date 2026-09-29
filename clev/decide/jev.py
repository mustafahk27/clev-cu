"""Jev (TypeSafe AI) decider: one `system_one` call answers next_action plus yes/no checks.

API per docs.typesafe.ai (summary in CLEV_PLAN.md §8). The only module importing typesafe_sdk.
"""

from __future__ import annotations

import time

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, NoulCriteria, RetryPolicy, TypeSafeError

from clev.core.errors import DeciderError
from clev.core.types import Decision, SerializedState, StepRecord
from clev.decide.questions import (
    NEXT_ACTION,
    NEXT_ACTION_INSTRUCTIONS,
    PROGRESS,
    YES_NO,
)
from clev.state.serialize import history_lines


def make_client(
    api_key: str, base_url: str | None, model: str, timeout_s: float
) -> AsyncTypeSafeClient:
    return AsyncTypeSafeClient(
        api_key=api_key,
        base_url=base_url or None,
        model=model,
        timeout=timeout_s,
        retry=RetryPolicy(max_retries=2, timeout=timeout_s),
    )


def option_description(line: str) -> str:
    """Option line without its label: '  4 type searchbox ...' -> 'type searchbox ...'."""
    parts = line.strip().split(" ", 1)
    return parts[1] if len(parts) == 2 else line.strip()


def build_questions(state: SerializedState, has_history: bool) -> dict:
    criteria = {o.label: option_description(o.line) for o in state.options}
    questions = {NEXT_ACTION: Choice(instructions=NEXT_ACTION_INSTRUCTIONS, criteria=criteria)}
    for qid, q in YES_NO.items():
        if qid == PROGRESS and not has_history:
            continue  # nothing to compare yet
        questions[qid] = Noul(
            instructions=q.instructions, criteria=NoulCriteria(true=q.true, false=q.false)
        )
    return questions


def build_state(state: SerializedState, history: list[StepRecord]) -> dict:
    recent = history_lines(history)
    return {
        # Options travel as the choice question's criteria, not in the state.
        "screen": state.header.removesuffix("\nOPTIONS:"),
        "recent_actions": recent or ["(none yet)"],
        "last_action": recent[-1] if recent else None,
    }


class JevDecider:
    def __init__(self, client: AsyncTypeSafeClient, price_per_billion_input: float = 42.0):
        self.client = client
        self.price_per_billion_input = price_per_billion_input

    async def decide(
        self, state: SerializedState, subgoal: str, history: list[StepRecord]
    ) -> Decision:
        start = time.perf_counter()
        steps = [r for r in history if r.event == "step" and r.decision]
        try:
            response = await self.client.system_one(
                state=build_state(state, history),
                questions=build_questions(state, has_history=bool(steps)),
            )
        except TypeSafeError as e:
            raise DeciderError(f"Jev call failed: {type(e).__name__}: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000

        answer = response.choices[NEXT_ACTION]
        label = answer.choice
        option = state.option(label)
        tokens_in = (response.usage.input_tokens or 0) if response.usage else 0
        return Decision(
            action=option.action.model_copy() if option and option.action else None,
            confidence=answer.confidence,
            probs=dict(answer.probabilities),
            decided_by="jev",
            latency_ms=latency_ms,
            cost_usd=tokens_in * self.price_per_billion_input / 1e9,
            chosen_label=label,
            checks={qid: a.noul for qid, a in response.nouls.items()},
        )

    async def check(self, state: SerializedState, question: str) -> float:
        try:
            response = await self.client.system_one(
                state={"screen": state.text}, questions={"q": Noul(instructions=question)}
            )
        except TypeSafeError as e:
            raise DeciderError(f"Jev call failed: {e}") from e
        return response.nouls["q"].noul

    async def aclose(self) -> None:
        await self.client.aclose()
