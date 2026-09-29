from clev.core.types import Action, Decision, Observation, StepRecord
from clev.trace.replay import step_line, summarize
from tests.fakes import el

OBS = Observation(app="a", title="t", elements=[el("e0", "link", "History")])


def step(n, who, escalated=False, reason=None, latency=100.0):
    return StepRecord(
        run_id="r",
        step=n,
        subgoal="Open History",
        observation=OBS,
        executed=True,
        decision=Decision(
            action=Action(kind="click", element_id="e0"),
            confidence=0.9,
            decided_by=who,
            chosen_label="1",
            latency_ms=latency,
            escalated=escalated,
            escalation_reason=reason,
            primary_choice="3" if escalated else None,
            primary_confidence=0.41 if escalated else None,
        ),
    )


RECORDS = [
    StepRecord(run_id="r", step=0, subgoal="", event="plan", subgoals=["Open History"]),
    step(1, "jev", latency=300),
    step(2, "llm", escalated=True, reason="low confidence 0.41 < 0.6", latency=2300),
    step(3, "jev", latency=200),
    StepRecord(
        run_id="r",
        step=3,
        subgoal="",
        event="end",
        note="success: all subgoals done",
        cost_usd=0.0021,
        latency_ms=4000,
    ),  # fmt: skip
]


def test_step_lines_show_decider_and_escalation():
    assert "jev  p=0.90" in step_line(RECORDS[1]) and "click link 'History'" in step_line(
        RECORDS[1]
    )
    escalated = step_line(RECORDS[2])
    assert "escalated: jev had 3 p=0.41; low confidence 0.41 < 0.6" in escalated
    assert "1. Open History" in step_line(RECORDS[0])


def test_summary_counts_and_rates():
    s = summarize(RECORDS)
    assert s.steps == 3 and s.decided_by == {"jev": 2, "llm": 1}
    assert round(s.escalation_rate, 2) == 0.33
    assert s.escalations == ["low confidence"]
    text = "\n".join(s.lines())
    assert "jev decision latency: median 250 ms" in text
    assert "escalated x1: low confidence" in text
    assert "result: success" in text and "cost: $0.0021" in text
