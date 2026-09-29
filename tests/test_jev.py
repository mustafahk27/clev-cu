"""Jev adapter and escalation policy, with a fake TypeSafe client (no network)."""

from types import SimpleNamespace

import pytest
from typesafe_sdk import Choice, Noul, TypeSafeError

from clev.core.errors import DeciderError
from clev.core.types import Action, Decision, Observation, StepRecord
from clev.decide.escalate import EscalatingDecider, Policy
from clev.decide.jev import JevDecider, build_questions, option_description
from clev.decide.questions import ERROR_VISIBLE, NEXT_ACTION, PROGRESS, SUBGOAL_COMPLETE
from clev.state.serialize import build_state
from tests.fakes import el


def page():
    return Observation(
        app="chromium",
        title="Wikipedia",
        url="https://www.wikipedia.org/",
        elements=[
            el("e0", "searchbox", "Search Wikipedia", editable=True),
            el("e1", "button", "Search"),
            el("e2", "link", "English"),
        ],
    )


STATE = build_state(page(), 'Type "Karachi" into the search box')
SEARCH = next(o.label for o in STATE.options if o.action and o.action.element_id == "e0")
ENGLISH = next(o.label for o in STATE.options if o.action and o.action.element_id == "e2")


class FakeClient:
    def __init__(self, choice, probs=None, confidence=0.95, nouls=None, error=None):
        self.choice, self.probs, self.confidence = choice, probs or {choice: 0.95}, confidence
        self.nouls = nouls or {}
        self.error = error
        self.calls = []

    async def system_one(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices={
                NEXT_ACTION: SimpleNamespace(
                    choice=self.choice, probabilities=self.probs, confidence=self.confidence
                )
            },
            nouls={
                q: SimpleNamespace(noul=self.nouls.get(q, 0.05))
                for q in questions
                if q != NEXT_ACTION
            },
            usage=SimpleNamespace(input_tokens=2000, output_tokens=50),
        )

    async def aclose(self):
        pass


class FakeLLMDecider:
    def __init__(self, label=ENGLISH):
        self.label = label
        self.calls = 0

    async def decide(self, state, subgoal, history):
        self.calls += 1
        option = state.option(self.label)
        return Decision(
            action=option.action,
            confidence=1.0,
            probs={self.label: 1.0},
            decided_by="llm",
            latency_ms=2000,
            cost_usd=0.0005,
            chosen_label=self.label,
        )

    async def check(self, state, question):
        return 0.0


# --- adapter -------------------------------------------------------------------------------


def test_questions_use_option_labels_and_descriptions():
    qs = build_questions(STATE, has_history=False)
    assert isinstance(qs[NEXT_ACTION], Choice)
    criteria = qs[NEXT_ACTION].criteria
    assert list(criteria) == [o.label for o in STATE.options]
    assert criteria[SEARCH] == "type searchbox 'Search Wikipedia'"
    assert criteria["STUCK"] == "stuck, need help"
    assert isinstance(qs[SUBGOAL_COMPLETE], Noul) and ERROR_VISIBLE in qs
    assert PROGRESS not in qs  # nothing to compare on the first step
    assert PROGRESS in build_questions(STATE, has_history=True)


def test_option_description_strips_label():
    assert option_description("  12 click link 'History'") == "click link 'History'"
    assert option_description("SUBGOAL_DONE the current goal") == "the current goal"


async def test_jev_decision_maps_answer():
    client = FakeClient(SEARCH, probs={SEARCH: 0.97, ENGLISH: 0.02}, confidence=0.96,
                        nouls={SUBGOAL_COMPLETE: 0.03})  # fmt: skip
    d = await JevDecider(client, price_per_billion_input=42).decide(STATE, "g", [])
    assert d.decided_by == "jev" and d.chosen_label == SEARCH
    assert d.action.kind == "type" and d.action.element_id == "e0"
    assert d.confidence == 0.96 and d.probs[SEARCH] == 0.97
    assert d.checks[SUBGOAL_COMPLETE] == 0.03 and ERROR_VISIBLE in d.checks
    assert d.cost_usd == pytest.approx(2000 * 42 / 1e9)
    sent = client.calls[0]["state"]
    assert sent["screen"].startswith("APP: chromium") and "OPTIONS" not in sent["screen"]
    assert sent["recent_actions"] == ["(none yet)"]


async def test_jev_errors_become_decider_errors():
    client = FakeClient(SEARCH, error=TypeSafeError("rate limited"))
    with pytest.raises(DeciderError, match="rate limited"):
        await JevDecider(client).decide(STATE, "g", [])


# --- escalation policy ---------------------------------------------------------------------


def escalating(client, llm=None, **policy):
    llm = llm or FakeLLMDecider()
    return EscalatingDecider(JevDecider(client), llm, Policy(**policy)), llm


async def test_confident_jev_is_accepted_without_llm():
    decider, llm = escalating(FakeClient(SEARCH, probs={SEARCH: 0.95, ENGLISH: 0.05}))
    d = await decider.decide(STATE, "g", [])
    assert d.decided_by == "jev" and not d.escalated and llm.calls == 0


@pytest.mark.parametrize(
    ("client", "reason"),
    [
        (FakeClient(SEARCH, confidence=0.4), "low confidence"),
        (FakeClient(SEARCH, probs={SEARCH: 0.5, ENGLISH: 0.45}, confidence=0.7), "top two options"),
        (FakeClient("NONE_OF_THESE", probs={"NONE_OF_THESE": 0.9}), "jev chose NONE_OF_THESE"),
        (FakeClient("STUCK", probs={"STUCK": 0.9}), "jev chose STUCK"),
    ],
)
async def test_escalation_triggers(client, reason):
    decider, llm = escalating(client)
    d = await decider.decide(STATE, "g", [])
    assert d.escalated and d.decided_by == "llm" and llm.calls == 1
    assert d.escalation_reason.startswith(reason)
    # Jev's own answer is kept for calibration analysis.
    assert d.primary_choice == client.choice and d.primary_confidence == client.confidence
    assert d.cost_usd == pytest.approx(0.0005 + 2000 * 42 / 1e9)
    assert d.latency_ms > 2000


async def test_jev_failure_falls_back_to_llm():
    decider, llm = escalating(FakeClient(SEARCH, error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):  # non-SDK errors are bugs: don't hide them
        await decider.decide(STATE, "g", [])

    class Down:
        async def decide(self, *a):
            raise DeciderError("Jev call failed: overloaded")

    decider = EscalatingDecider(Down(), llm)
    d = await decider.decide(STATE, "g", [])
    assert d.escalated and d.escalation_reason.startswith("jev error")


async def test_subgoal_complete_and_error_become_control_signals():
    done, llm = escalating(FakeClient(SEARCH, nouls={SUBGOAL_COMPLETE: 0.9}))
    d = await done.decide(STATE, "g", [])
    assert d.chosen_label == "SUBGOAL_DONE" and d.action is None and d.decided_by == "jev"
    assert "subgoal complete (0.90)" in d.escalation_reason and llm.calls == 0

    err, _ = escalating(FakeClient(SEARCH, nouls={ERROR_VISIBLE: 0.85, SUBGOAL_COMPLETE: 0.9}))
    d = await err.decide(STATE, "g", [])
    assert d.chosen_label == "STUCK" and "error visible" in d.escalation_reason


def executed(label, subgoal="g", progress=None, escalated=False, obs=None):
    option = STATE.option(label)
    checks = {PROGRESS: progress} if progress is not None else {}
    return StepRecord(
        run_id="r",
        step=1,
        subgoal=subgoal,
        observation=obs or page(),
        executed=True,
        decision=Decision(
            action=option.action,
            confidence=0.9,
            decided_by="jev",
            chosen_label=label,
            checks=checks,
            escalated=escalated,
        ),  # fmt: skip
    )


async def test_repeat_and_no_progress_escalate():
    client = FakeClient(ENGLISH, probs={ENGLISH: 0.95})
    decider, _ = escalating(client)
    d = await decider.decide(STATE, "g", [executed(ENGLISH), executed(ENGLISH)])
    assert d.escalated and d.escalation_reason == "same action 3 times in a row"

    client = FakeClient(SEARCH, probs={SEARCH: 0.95})
    decider, _ = escalating(client)
    history = [
        executed(ENGLISH, progress=0.2),
        executed(SEARCH, progress=0.1),
        executed(ENGLISH, progress=0.3),
    ]
    d = await decider.decide(STATE, "g", history)
    assert d.escalated and d.escalation_reason == "no progress for 3 steps"


async def test_two_escalations_without_progress_replan():
    client = FakeClient(SEARCH, probs={SEARCH: 0.95}, nouls={PROGRESS: 0.1})
    decider, _ = escalating(client)
    history = [executed(ENGLISH, escalated=True), executed(SEARCH, escalated=True)]
    d = await decider.decide(STATE, "g", history)
    assert d.chosen_label == "STUCK" and "2 escalations" in d.escalation_reason


async def test_repeat_check_matches_by_name_not_id():
    # Same element, new id after re-observation: still a repeat.
    moved = page()
    moved.elements[2] = moved.elements[2].model_copy(update={"id": "e9"})
    old = executed(ENGLISH, obs=moved)
    old.decision.action = Action(kind="click", element_id="e9")
    client = FakeClient(ENGLISH, probs={ENGLISH: 0.95})
    decider, _ = escalating(client)
    d = await decider.decide(STATE, "g", [old, old])
    assert d.escalated
