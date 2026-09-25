"""MockDecider: deterministic heuristic decider for offline development and tests.

Policy: within a subgoal, act once on the best option sharing a word with the goal (Enter for
"press Enter" subgoals), then declare the subgoal done; NONE_OF_THESE if nothing matches.
No model calls, no cost.
"""

from __future__ import annotations

import time

from clev.core.types import Decision, SerializedState, StepRecord
from clev.state.goal import Goal, tokens
from clev.state.rank import score


class MockDecider:
    async def decide(
        self, state: SerializedState, subgoal: str, history: list[StepRecord]
    ) -> Decision:
        start = time.perf_counter()
        acted = any(
            r.event == "step" and r.subgoal == subgoal and r.executed and not r.error
            for r in history
        )
        if acted:
            label = "SUBGOAL_DONE"
        elif "press enter" in subgoal.lower() or "submit the search" in subgoal.lower():
            label = "PRESS_ENTER"
        else:
            goal = Goal.parse(subgoal)
            # Only elements sharing a word with the goal qualify; otherwise NONE_OF_THESE.
            scored = [
                (score(e, goal), label)
                for label, e in state.elements.items()
                if goal.tokens & set(tokens(e.name))
            ]
            label = max(scored)[1] if scored else "NONE_OF_THESE"
        option = state.option(label)
        return Decision(
            action=option.action.model_copy() if option and option.action else None,
            confidence=1.0,
            probs={label: 1.0},
            decided_by="mock",
            latency_ms=(time.perf_counter() - start) * 1000,
            chosen_label=label,
        )

    async def check(self, state: SerializedState, question: str) -> float:
        return 0.0
