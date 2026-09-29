"""Control loop: plan, then each step observe -> serialize -> decide -> gate -> act -> trace."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from clev.config import Settings
from clev.core.errors import ClevError
from clev.core.interfaces import Decider, Executor, Observer, Planner, Tracer
from clev.core.types import Action, Decision, Observation, SerializedState, StepRecord
from clev.safety.gate import SafetyGate
from clev.state.goal import Goal
from clev.state.serialize import build_state, describe_action

MAX_CONSECUTIVE_ERRORS = 3
REPEAT_LIMIT = 3  # same action on the same element this many times in a row -> replan


@dataclass
class RunResult:
    success: bool
    reason: str
    steps: int
    cost_usd: float
    seconds: float
    done: list[str] = field(default_factory=list)


@dataclass
class _Run:
    task: str
    subgoals: list[str]
    done: list[str] = field(default_factory=list)
    history: list[StepRecord] = field(default_factory=list)
    signatures: list[tuple] = field(default_factory=list)  # executed actions, for loop detection
    step: int = 0
    replans: int = 0
    errors_in_a_row: int = 0
    cost_usd: float = 0.0


class _Stop(Exception):
    def __init__(self, success: bool, reason: str):
        self.success, self.reason = success, reason


class Agent:
    def __init__(
        self,
        *,
        observer: Observer,
        executor: Executor,
        decider: Decider,
        planner: Planner,
        gate: SafetyGate,
        tracer: Tracer,
        settings: Settings,
        run_id: str = "run",
        on_event: Callable[[str], None] | None = None,
    ):
        self.observer = observer
        self.executor = executor
        self.decider = decider
        self.planner = planner
        self.gate = gate
        self.tracer = tracer
        self.settings = settings
        self.run_id = run_id
        self.on_event = on_event or (lambda _msg: None)

    async def run(self, task: str) -> RunResult:
        start = time.perf_counter()
        run = _Run(task=task, subgoals=[])
        success, reason = False, "interrupted"
        try:
            await self._plan(run)
            while True:
                if not run.subgoals:
                    raise _Stop(True, "all subgoals done")
                if run.step >= self.settings.max_steps:
                    raise _Stop(False, f"step cap ({self.settings.max_steps}) reached")
                await self._step(run)
        except _Stop as stop:
            success, reason = stop.success, stop.reason
        except ClevError as e:  # model call failed after retries, page unreadable, etc.
            success, reason = False, f"error: {e}"
        except Exception as e:  # a bug: record it, then let it surface
            success, reason = False, f"crashed: {type(e).__name__}: {e}"
            raise
        finally:
            # Also runs on Ctrl+C / errors, so every trace ends with an "end" record.
            seconds = time.perf_counter() - start
            self._record(
                StepRecord(
                    run_id=self.run_id,
                    step=run.step,
                    subgoal=run.subgoals[0] if run.subgoals else "",
                    event="end",
                    note=f"{'success' if success else 'failed'}: {reason}",
                    cost_usd=run.cost_usd,
                    latency_ms=seconds * 1000,
                )
            )
            self.on_event(f"{'✓' if success else '✗'} {reason}")
        return RunResult(success, reason, run.step, run.cost_usd, seconds, run.done)

    # --- planning ------------------------------------------------------------------------

    async def _plan(self, run: _Run) -> None:
        obs = await self.observer.observe()
        cost_before = self.planner.cost_usd
        plan = await self.planner.plan(run.task, obs)
        cost = self.planner.cost_usd - cost_before
        run.cost_usd += cost
        run.subgoals = list(plan.subgoals)
        self._record(
            StepRecord(
                run_id=self.run_id,
                step=0,
                subgoal="",
                event="plan",
                subgoals=run.subgoals,
                note=f"start_url={plan.start_url}",
                cost_usd=cost,
            )
        )
        self.on_event("plan: " + " | ".join(run.subgoals))
        if plan.start_url:
            action = Action(kind="goto", url=plan.start_url)
            verdict = await self.gate.check(action, obs)
            if not verdict.allowed:
                raise _Stop(False, verdict.reason or "start URL blocked")
            self.on_event(f"open {plan.start_url}")
            await self.executor.execute(action, obs)

    async def _replan(self, run: _Run, obs: Observation, reason: str) -> None:
        if run.replans >= self.settings.max_replans:
            raise _Stop(False, f"gave up after {run.replans} replans ({reason})")
        run.replans += 1
        cost_before = self.planner.cost_usd
        run.subgoals = await self.planner.replan(run.task, run.done, obs, reason)
        cost = self.planner.cost_usd - cost_before
        run.cost_usd += cost
        run.signatures.clear()
        run.errors_in_a_row = 0
        self._record(
            StepRecord(
                run_id=self.run_id,
                step=run.step,
                subgoal="",
                event="replan",
                subgoals=run.subgoals,
                note=reason,
                cost_usd=cost,
            )
        )
        self.on_event(f"replan ({reason}): " + " | ".join(run.subgoals))

    # --- one step ------------------------------------------------------------------------

    async def _step(self, run: _Run) -> None:
        run.step += 1
        started = time.perf_counter()
        planner_cost_before = self.planner.cost_usd
        subgoal = run.subgoals[0]
        s = self.settings

        obs = await self.observer.observe()
        state = build_state(obs, subgoal, run.done, s.max_options, s.token_budget)
        decision = await self.decider.decide(state, subgoal, run.history)
        rec = StepRecord(
            run_id=self.run_id,
            step=run.step,
            subgoal=subgoal,
            observation=self._trace_view(obs, state, decision),
            state_text=state.text,
            decision=decision,
            escalated=decision.escalated,
            escalation_reason=decision.escalation_reason,
            checks=decision.checks,
        )
        replan_reason = await self._act(run, rec, obs, subgoal, decision)

        rec.cost_usd = decision.cost_usd + (self.planner.cost_usd - planner_cost_before)
        rec.latency_ms = (time.perf_counter() - started) * 1000
        run.cost_usd += rec.cost_usd
        run.history.append(rec)
        self._record(rec)
        self.on_event(self._describe(rec))
        if replan_reason:
            await self._replan(run, obs, replan_reason)

    async def _act(
        self, run: _Run, rec: StepRecord, obs: Observation, subgoal: str, decision: Decision
    ) -> str | None:
        """Carry out the decision. Returns a reason to replan, or None."""
        label, action = decision.chosen_label, decision.action
        if label == "SUBGOAL_DONE":
            run.done.append(run.subgoals.pop(0))
            rec.note = "subgoal done" + (
                f" ({decision.escalation_reason})" if decision.escalation_reason else ""
            )
            return None
        if action is None or label in ("NONE_OF_THESE", "STUCK"):
            why = f": {decision.escalation_reason}" if decision.escalation_reason else ""
            return f"decider chose {label} for {subgoal!r}{why}"

        goal = Goal.parse(subgoal)
        if action.kind == "type" and action.text is None:
            action.text = goal.literal
            if action.text is None:  # plan §10: only call the LLM when no literal is given
                target = obs.element(action.element_id)
                action.text = await self.planner.write_text(run.task, subgoal, target)

        verdict = await self.gate.check(action, obs)
        if not verdict.allowed:
            rec.blocked_by_safety = verdict.reason
            if verdict.stop:
                raise _Stop(False, verdict.reason or "blocked by safety gate")
            return None
        if verdict.reason:
            rec.note = verdict.reason

        if self.settings.dry_run:
            rec.note = "dry run: not executed"
            run.done.append(run.subgoals.pop(0))  # nothing changes on screen, so move on
            return None

        try:
            await self.executor.execute(action, obs)
        except ClevError as e:
            rec.error = str(e)
            run.errors_in_a_row += 1
            if run.errors_in_a_row >= MAX_CONSECUTIVE_ERRORS:
                return f"{run.errors_in_a_row} failed actions in a row (last: {e})"
            return None
        rec.executed = True
        run.errors_in_a_row = 0

        signature = self._signature(action, obs)
        run.signatures.append(signature)
        if len(run.signatures) >= REPEAT_LIMIT and len(set(run.signatures[-REPEAT_LIMIT:])) == 1:
            return f"repeated the same action {REPEAT_LIMIT} times: {describe_action(action, obs)}"

        # Typing the subgoal's quoted value completes it; skip a decider call to say so.
        if action.kind == "type" and goal.is_typing and goal.literal is not None:
            run.done.append(run.subgoals.pop(0))
            rec.note = "typed the subgoal's value; subgoal done"
        return None

    # --- helpers -------------------------------------------------------------------------

    def _trace_view(
        self, obs: Observation, state: SerializedState, decision: Decision
    ) -> Observation:
        if self.settings.trace_full_observations:
            return obs
        keep = {e.id for e in state.elements.values()}
        if decision.action and decision.action.element_id:
            keep.add(decision.action.element_id)
        return obs.model_copy(update={"elements": [e for e in obs.elements if e.id in keep]})

    @staticmethod
    def _signature(action: Action, obs: Observation) -> tuple:
        target = obs.element(action.element_id) if action.element_id else None
        who = (target.role, target.name) if target else None
        return (action.kind, who, action.text, action.key, action.direction)

    @staticmethod
    def _describe(rec: StepRecord) -> str:
        d = rec.decision
        what = describe_action(d.action, rec.observation, d.chosen_label) if d else "-"
        outcome = (
            f"error: {rec.error}"
            if rec.error
            else f"blocked: {rec.blocked_by_safety}"
            if rec.blocked_by_safety
            else rec.note or ("ok" if rec.executed else "")
        )
        who = d.decided_by if d else "-"
        if d and d.escalated:
            outcome += f"; escalated: {d.escalation_reason}"
        conf = f" p={d.confidence:.2f}" if d and d.decided_by == "jev" else ""
        ms = f" {d.latency_ms:.0f}ms" if d else ""
        return f"[{rec.step:>2}] {who:<4}{conf}{ms} {rec.subgoal[:45]:<45} -> {what}  ({outcome})"

    def _record(self, rec: StepRecord) -> None:
        self.tracer.record(rec)
