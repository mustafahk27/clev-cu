"""Test doubles for the Phase 4 loop: no network, no models."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from clev.core.errors import ActionError
from clev.core.interfaces import LLMResult
from clev.core.types import Action, Element, Observation, Plan


class FakeLLM:
    """LLMClient returning scripted outputs. `reply(schema, system, user)` builds each answer."""

    def __init__(self, reply: Callable[[type[BaseModel], str, str], dict], cost: float = 0.001):
        self.reply = reply
        self.cost = cost
        self.calls: list[dict] = []

    async def complete(self, *, model, system, user, schema, max_output_tokens=1000):
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema})
        parsed = schema.model_validate(self.reply(schema, system, user))
        return LLMResult[schema](
            parsed=parsed, input_tokens=100, output_tokens=10, cost_usd=self.cost
        )


class FakePlanner:
    def __init__(self, subgoals, start_url=None, replans=None, text="written text"):
        self.subgoals = list(subgoals)
        self.start_url = start_url
        self.replans = list(replans or [])  # successive replan results
        self.text = text
        self.cost_usd = 0.0
        self.replan_reasons: list[str] = []
        self.write_calls = 0

    async def plan(self, task, obs):
        self.cost_usd += 0.01
        return Plan(start_url=self.start_url, subgoals=self.subgoals)

    async def replan(self, task, done, obs, reason):
        self.cost_usd += 0.01
        self.replan_reasons.append(reason)
        return self.replans.pop(0) if self.replans else []

    async def write_text(self, task, subgoal, field):
        self.cost_usd += 0.005
        self.write_calls += 1
        return self.text


class FakeTracer:
    def __init__(self):
        self.records = []

    def record(self, step):
        self.records.append(step)

    def close(self):
        pass


def el(id, role="button", name="", **kw) -> Element:
    return Element(id=id, role=role, name=name, **kw)


class FakeSite:
    """A tiny scripted website, acting as both Observer and Executor.

    Pages are element lists. Clicking an element whose name equals a page key goes there
    ("Search" -> "search"); Enter goes to `on_enter`; typing sets the field's value.
    """

    def __init__(self, pages: dict[str, list[Element]], start: str = "home", on_enter=None):
        self.pages = pages
        self.page = start
        self.on_enter = on_enter
        self.values: dict[str, str] = {}
        self.executed: list[Action] = []
        self.fail_next = 0

    async def observe(self) -> Observation:
        elements = [
            e.model_copy(update={"value": self.values.get(e.id, e.value)})
            for e in self.pages[self.page]
        ]
        return Observation(
            app="fake", title=self.page, url=f"https://fake.test/{self.page}", elements=elements
        )

    async def execute(self, action: Action, obs: Observation) -> None:
        if self.fail_next:
            self.fail_next -= 1
            raise ActionError("element not clickable")
        self.executed.append(action)
        target = obs.element(action.element_id) if action.element_id else None
        if action.kind == "type":
            self.values[action.element_id] = action.text
        elif action.kind == "goto":
            self.page = action.url.rsplit("/", 1)[-1]
        elif action.kind == "key" and action.key == "enter" and self.on_enter:
            self.page = self.on_enter
        elif action.kind == "click" and target is not None and target.name.lower() in self.pages:
            self.page = target.name.lower()
