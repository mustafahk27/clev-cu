"""Protocols for every external dependency.

Vendor SDKs (Jev, Anthropic, Playwright, pyobjc) are only imported inside adapter modules
that implement these protocols. Nothing else imports them directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clev.core.types import (
    Action,
    Decision,
    Element,
    Observation,
    SerializedState,
    StepRecord,
)


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
    async def plan(self, task: str, obs: Observation) -> list[str]: ...

    async def write_text(self, task: str, subgoal: str, field: Element) -> str: ...

    async def replan(
        self, task: str, done: list[str], obs: Observation, reason: str
    ) -> list[str]: ...


@runtime_checkable
class Executor(Protocol):
    async def execute(self, action: Action, obs: Observation) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    def record(self, step: StepRecord) -> None: ...

    def close(self) -> None: ...
