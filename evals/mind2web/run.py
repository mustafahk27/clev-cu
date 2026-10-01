"""Run deciders over Mind2Web steps and record per-step results.

Every decider sees the same Clev pipeline output (observer -> filter -> rank -> serialize), so
the comparison isolates the decider (plan §14). Answers are cached in evals/cache/ so re-runs
and report tweaks don't spend money again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from clev.core.interfaces import Decider
from clev.core.types import Observation, SerializedState
from clev.observe.browser import BrowserSession
from clev.state.serialize import build_state
from evals.mind2web.loader import Step, load_dev_steps, load_steps
from evals.mind2web.render import Mind2WebRenderer

CACHE_FILE = Path("evals/cache/mind2web.jsonl")


def input_hash(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:12]


@dataclass
class Prepared:
    step: Step
    states: dict[int, SerializedState]  # max_options -> state
    strict: set[str]
    equivalent: set[str]
    target_in_html: bool
    observed: bool  # observer saw the target (or an equivalent element)
    n_candidates: int
    obs: Observation | None = None  # kept for re-serializing with a planner-written subgoal


@dataclass
class Answer:
    uid: str
    decider: str
    max_options: int
    label: str | None = None
    element_id: str | None = None
    verb: str | None = None
    confidence: float | None = None
    margin: float | None = None  # top-1 minus top-2 probability (Jev)
    checks: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens: int = 0  # serialized-state estimate
    error: str | None = None
    subgoal: str | None = None  # the goal the decider was given, when not the whole task
    input_hash: str = ""  # hash of exactly what the model saw; changes invalidate the cache

    @property
    def key(self) -> str:
        return f"{self.uid}|{self.decider}|{self.max_options}|{self.input_hash}"


async def prepare(steps: list[Step], option_counts: list[int], log=print) -> list[Prepared]:
    prepared = []
    async with BrowserSession(headless=True) as session:
        renderer = Mind2WebRenderer(session)
        for i, step in enumerate(steps, 1):
            r = await renderer.render(step.html, step.website, step.target_ids)
            states = {
                k: build_state(r.obs, step.task, step.history, k, anchor=step.last_target)
                for k in option_counts
            }
            candidates = states[max(option_counts)].elements
            prepared.append(
                Prepared(
                    step=step,
                    states=states,
                    strict=r.strict,
                    equivalent=r.equivalent,
                    target_in_html=r.target_in_html,
                    observed=bool(r.equivalent),
                    n_candidates=len(candidates),
                    obs=r.obs,
                )
            )
            if i % 100 == 0:
                log(f"  rendered {i}/{len(steps)} steps")
    return prepared


def load_cache() -> dict[str, Answer]:
    if not CACHE_FILE.exists():
        return {}
    answers = {}
    for line in CACHE_FILE.read_text().splitlines():
        if line.strip():
            a = Answer(**json.loads(line))
            answers[a.key] = a
    return answers


def append_cache(answer: Answer) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("a") as f:
        f.write(json.dumps(asdict(answer)) + "\n")


async def decide_one(
    decider: Decider,
    name: str,
    p: Prepared,
    k: int,
    state: SerializedState | None = None,
    goal: str | None = None,
) -> Answer:
    state = state or p.states[k]
    answer = Answer(uid=p.step.action_uid, decider=name, max_options=k, tokens=state.token_estimate)
    answer.subgoal = goal
    start = time.perf_counter()
    try:
        d = await decider.decide(state, goal or p.step.task, [])
    except Exception as e:  # recorded, scored as wrong; the run continues
        answer.error = f"{type(e).__name__}: {e}"[:300]
        answer.latency_ms = (time.perf_counter() - start) * 1000
        return answer
    top = sorted(d.probs.values(), reverse=True)
    answer.label = d.chosen_label
    answer.element_id = d.action.element_id if d.action else None
    answer.verb = d.action.kind if d.action else None
    answer.confidence = d.confidence
    answer.margin = top[0] - top[1] if len(top) > 1 else None
    answer.checks = d.checks
    answer.latency_ms = d.latency_ms
    answer.cost_usd = d.cost_usd
    return answer


async def run_decider(
    decider: Decider,
    name: str,
    prepared: list[Prepared],
    k: int,
    cache: dict[str, Answer],
    concurrency: int,
    log: Callable[[str], None] = print,
) -> list[Answer]:
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(p: Prepared) -> Answer:
        nonlocal done
        h = input_hash(p.states[k].text)
        key = f"{p.step.action_uid}|{name}|{k}|{h}"
        if key in cache and cache[key].error is None:
            return cache[key]
        async with sem:
            a = await decide_one(decider, name, p, k)
        a.input_hash = h
        append_cache(a)
        done += 1
        if done % 50 == 0:
            log(f"  {name} @{k}: {done} new answers")
        return a

    return await asyncio.gather(*(one(p) for p in prepared))


async def run_all(
    n: int,
    runs: list[tuple[str, int]],
    make_decider: Callable[[str], Decider],
    concurrency: int = 8,
    seed: int = 0,
    log: Callable[[str], None] = print,
    dev: bool = False,
) -> tuple[list[Prepared], dict[tuple[str, int], list[Answer]]]:
    """`runs` = [(decider name, max_options), ...]. `dev`: train-split steps, for tuning."""
    steps = load_dev_steps(n, seed) if dev else load_steps(n, seed)
    log(f"Loaded {len(steps)} Mind2Web steps; rendering with the Clev observer...")
    prepared = await prepare(steps, sorted({k for _, k in runs}), log)
    cache = load_cache()
    results = {}
    for name, k in runs:
        log(f"Deciding with {name} (max_options={k})...")
        results[(name, k)] = await run_decider(
            make_decider(name), name, prepared, k, cache, concurrency, log
        )
    return prepared, results
