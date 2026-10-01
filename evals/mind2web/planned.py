"""Live-style variant: the planner writes the next subgoal, then deciders pick the element.

Mind2Web's standard setup gives the decider the whole task plus past actions, so the decider
must also plan. Live Clev splits that: the planner writes short subgoals and Jev picks elements.
Here, for each step, the real `LLMPlanner.replan` (the code live Clev uses when re-planning)
writes the next subgoal from the task, past actions and the page; every decider then gets that
same subgoal, so only the element choice differs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from clev.core.interfaces import Decider, LLMClient
from clev.planner.planner import LLMPlanner, describe_page
from clev.planner.prompts import REPLAN_SYSTEM
from clev.state.serialize import build_state
from evals.mind2web.run import Answer, Prepared, append_cache, decide_one, input_hash

REASON = "Starting from this page, what is the single next step toward the task?"


def plan_hash(p: Prepared) -> str:
    """Everything the planner sees, so prompt or page-description changes re-plan."""
    page = describe_page(p.obs, p.step.task)
    return input_hash(p.step.task, *p.step.history, page, REPLAN_SYSTEM, REASON)


async def plan_subgoal(llm: LLMClient, model: str, p: Prepared) -> Answer:
    planner = LLMPlanner(llm, model)  # one per step, so its cost counter is exact
    a = Answer(uid=p.step.action_uid, decider=f"plan:{model}", max_options=0)
    start = time.perf_counter()
    try:
        subgoals = await planner.replan(p.step.task, p.step.history, p.obs, REASON)
        a.subgoal = subgoals[0] if subgoals else p.step.task
    except Exception as e:
        a.error = f"{type(e).__name__}: {e}"[:300]
        a.subgoal = p.step.task  # fall back to the whole task
    a.latency_ms = (time.perf_counter() - start) * 1000
    a.cost_usd = planner.cost_usd
    a.input_hash = plan_hash(p)
    return a


async def run_planned(
    prepared: list[Prepared],
    llm: LLMClient,
    planner_model: str,
    deciders: dict[str, Decider],
    k: int,
    cache: dict[str, Answer],
    concurrency: int = 8,
    log: Callable[[str], None] = print,
) -> tuple[list[Answer], dict[str, list[Answer]]]:
    """(planner answers, {decider name + '+plan': answers})."""
    sem = asyncio.Semaphore(concurrency)

    async def cached(key: str, make) -> Answer:
        if key in cache and cache[key].error is None:
            return cache[key]
        async with sem:
            a = await make()
        append_cache(a)
        cache[a.key] = a
        return a

    log(f"Planning a next subgoal per step with {planner_model}...")
    plans = await asyncio.gather(
        *(
            cached(
                f"{p.step.action_uid}|plan:{planner_model}|0|{plan_hash(p)}",
                lambda p=p: plan_subgoal(llm, planner_model, p),
            )
            for p in prepared
        )
    )
    results = {}
    for name, decider in deciders.items():
        label = f"{name}+plan"
        log(f"Deciding with {label}...")

        def state_for(p, plan):
            return build_state(p.obs, plan.subgoal, p.step.history, k, anchor=p.step.last_target)

        async def make(p, plan, name=label, decider=decider):
            state = state_for(p, plan)
            a = await decide_one(decider, name, p, k, state, plan.subgoal)
            a.input_hash = input_hash(state.text)
            return a

        results[label] = await asyncio.gather(
            *(
                cached(
                    f"{p.step.action_uid}|{label}|{k}|{input_hash(state_for(p, plan).text)}",
                    lambda p=p, plan=plan: make(p, plan),
                )
                for p, plan in zip(prepared, plans, strict=True)
            )
        )
    return plans, results
