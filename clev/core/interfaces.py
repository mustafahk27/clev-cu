"""Protocols for every external dependency.

Vendor SDKs (Jev, OpenAI, Anthropic, Playwright, pyobjc) are only imported inside adapter modules
that implement these protocols. Nothing else imports them directly.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from clev.core.types import (
    Action,
    Decision,
    Element,
    Observation,
    Plan,
    SerializedState,
    StepRecord,
)

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class Observer(Protocol):
    async def observe(self) -> Observation: ...


@runtime_checkable
class Decider(Protocol):
    async def decide(
        self, state: SerializedState, subgoal: str, history: list[StepRecord]
    ) -> Decision: ...

    async def check(self, state: SerializedState, question: str) -> float: ...


@runtime_checkable
class Planner(Protocol):
    async def plan(self, task: str, obs: Observation) -> Plan: ...

    async def write_text(self, task: str, subgoal: str, field: Element) -> str: ...

    async def replan(
        self, task: str, done: list[str], obs: Observation, reason: str
    ) -> list[str]: ...

    @property
    def cost_usd(self) -> float:
        """Total spent on model calls so far (the loop attributes it to steps)."""
        ...


@runtime_checkable
class Executor(Protocol):
    async def execute(self, action: Action, obs: Observation) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    def record(self, step: StepRecord) -> None: ...

    def close(self) -> None: ...


class LLMResult(BaseModel, Generic[T]):
    parsed: T
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


@runtime_checkable
class LLMClient(Protocol):
    """One structured-output call. Adapters in clev/llm/ are the only code importing LLM SDKs."""

    async def complete(
        self, *, model: str, system: str, user: str, schema: type[T], max_output_tokens: int = 1000
    ) -> LLMResult[T]: ...
