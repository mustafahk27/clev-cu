"""LLM planner: task -> start URL + subgoals; writes free text; re-plans when stuck."""

from __future__ import annotations

from pydantic import BaseModel, Field

from clev.core.interfaces import LLMClient
from clev.core.types import Element, Observation, Plan
from clev.planner.prompts import PLAN_SYSTEM, REPLAN_SYSTEM, WRITE_SYSTEM
from clev.state.filter import filter_elements
from clev.state.rank import rank

PAGE_ELEMENTS = 60  # candidates shown to the planner: the most task-relevant, in page order


class _PlanOut(BaseModel):
    start_url: str | None = Field(description="https URL to open first, or null")
    subgoals: list[str]


class _SubgoalsOut(BaseModel):
    subgoals: list[str]


class _TextOut(BaseModel):
    text: str


def describe_page(obs: Observation | None, task: str | None = None) -> str:
    """Page title/URL plus up to PAGE_ELEMENTS candidates.

    With a task, the candidates most relevant to it are shown (in page order); without one, the
    first ones on the page. The first-N view missed most of a long page.
    """
    if obs is None or not (obs.url or "").startswith("http"):
        return "PAGE: (blank; no site open yet)"
    lines = [f"PAGE: {obs.title} | {obs.url}"]
    candidates = filter_elements(obs).candidates
    if task and len(candidates) > PAGE_ELEMENTS:
        order = {e.id: i for i, e in enumerate(candidates)}
        best = [e for e, _ in rank(candidates, task, obs.viewport)[:PAGE_ELEMENTS]]
        candidates = sorted(best, key=lambda e: order[e.id])
    for e in candidates[:PAGE_ELEMENTS]:
        lines.append(f"- {e.role} {e.name[:60]!r}" + (f" @ {e.context}" if e.context else ""))
    return "\n".join(lines)


class LLMPlanner:
    def __init__(self, llm: LLMClient, model: str):
        self.llm = llm
        self.model = model
        self.cost_usd = 0.0

    async def plan(self, task: str, obs: Observation) -> Plan:
        out = await self._call(PLAN_SYSTEM, f"TASK: {task}\n\n{describe_page(obs, task)}", _PlanOut)
        url = out.start_url if out.start_url and out.start_url.startswith("http") else None
        return Plan(start_url=url, subgoals=_clean(out.subgoals))

    async def replan(self, task: str, done: list[str], obs: Observation, reason: str) -> list[str]:
        done_text = "\n".join(f"{i}. {d}" for i, d in enumerate(done, 1)) or "(nothing yet)"
        user = f"TASK: {task}\nDONE:\n{done_text}\nREASON FOR REPLANNING: {reason}\n\n"
        out = await self._call(REPLAN_SYSTEM, user + describe_page(obs, task), _SubgoalsOut)
        return _clean(out.subgoals)

    async def write_text(self, task: str, subgoal: str, field: Element) -> str:
        user = f"TASK: {task}\nSUBGOAL: {subgoal}\nFIELD: {field.role} {field.name!r}"
        out = await self._call(WRITE_SYSTEM, user, _TextOut, max_output_tokens=800)
        return out.text

    async def _call(self, system: str, user: str, schema: type, max_output_tokens: int = 1200):
        result = await self.llm.complete(
            model=self.model,
            system=system,
            user=user,
            schema=schema,
            max_output_tokens=max_output_tokens,
        )
        self.cost_usd += result.cost_usd
        return result.parsed


def _clean(subgoals: list[str]) -> list[str]:
    return [s.strip() for s in subgoals if s and s.strip()][:20]
