"""Offline tests for the Mind2Web eval: parsing, rendering, scoring, simulation, report."""

import json

import pytest

from clev.core.types import Observation
from clev.state.serialize import build_state
from evals.mind2web.loader import Step, parse_row
from evals.mind2web.render import Mind2WebRenderer, prepare_html
from evals.mind2web.run import Answer, Prepared
from evals.report import (
    Policy,
    action_ok,
    calibration,
    element_ok,
    escalate_outcomes,
    plain,
    row_from_outcomes,
    write_report,
)

pytest.importorskip("matplotlib")


def test_parse_row():
    row = {
        "action_uid": "u1",
        "cleaned_html": "<html></html>",
        "operation": json.dumps({"op": "TYPE", "value": "08817", "original_op": "TYPE"}),
        "pos_candidates": [json.dumps({"tag": "input", "backend_node_id": "42"})],
        "website": "budget",
        "domain": "Travel",
        "annotation_id": "a1",
        "confirmed_task": "Rent a truck",
        "action_reprs": ["[link] Trucks -> CLICK", "[textbox] Zip -> TYPE: 08817"],
        "target_action_index": "1",
    }
    s = parse_row(row, "test_task")
    assert (s.op, s.value, s.target_ids, s.previous) == (
        "TYPE",
        "08817",
        ["42"],
        ["[link] Trucks -> CLICK"],
    )
    assert s.expected_verb == "type"


def test_prepare_html_restores_links_and_aria():
    html = '<a backend_node_id="1"><text>Go</text></a><a href="/x">X</a><button aria_label="Close">'
    fixed = prepare_html(html)
    assert '<a href="#" backend_node_id="1">' in fixed and '<a href="/x">' in fixed
    assert 'aria-label="Close"' in fixed


HTML = """<html backend_node_id="1"><body backend_node_id="2">
  <a backend_node_id="10"><span backend_node_id="11">Budget Truck</span></a>
  <label backend_node_id="20">Pick-up time</label>
  <select backend_node_id="21" id="t"><option>1 PM</option></select>
  <label backend_node_id="30"><input backend_node_id="31" type="checkbox"> Pads</label>
  <button backend_node_id="40">Find</button>
</body></html>"""


async def test_renderer_maps_targets_strict_and_equivalent(browser_session):
    r = Mind2WebRenderer(browser_session)
    link = await r.render(HTML, "budget", ["10"])
    by_backend = {v: k for k, v in link.backend_ids.items()}
    assert link.target_in_html and link.strict == {by_backend["10"]}
    assert link.obs.title == "budget"
    # Target is the <span> inside the link: clicking our link is equivalent, not strict.
    inner = await r.render(HTML, "budget", ["11"])
    assert not inner.strict and inner.equivalent == {by_backend["10"]}
    # Target is a <label> wrapping a checkbox: our checkbox is equivalent.
    label = await r.render(HTML, "budget", ["30"])
    assert label.equivalent == {by_backend["31"]}
    missing = await r.render(HTML, "budget", ["999"])
    assert not missing.target_in_html and not missing.equivalent


def step(uid, op="CLICK"):
    return Step(uid, "test_task", "site", "d", "task", "", op, "", ["x"], [])


def prep(uid, target_id="e1", op="CLICK", in_html=True):
    state = build_state(Observation(app="a", title="t"), "task")
    states = {k: state for k in (50, 100, 200)}
    return Prepared(step(uid, op), states, {target_id}, {target_id}, in_html, in_html, 10)


def ans(uid, element_id="e1", verb="click", conf=0.9, margin=0.5, label="1", decider="jev",
        latency=500.0, cost=0.0002, checks=None, error=None):  # fmt: skip
    return Answer(uid, decider, 200, label, element_id, verb, conf, margin, checks or {},
                  latency, cost, 3000, error)  # fmt: skip


def test_scoring():
    p = prep("a", op="TYPE")
    assert element_ok(ans("a"), p) and not action_ok(ans("a"), p)
    assert action_ok(ans("a", verb="type"), p)
    assert not element_ok(ans("a", element_id="e2"), p)
    assert not element_ok(ans("a", error="boom"), p)


def test_escalation_simulation_and_rows():
    prepared = [prep(u) for u in "abcd"]
    jev = [
        ans("a"),  # confident, right
        ans("b", element_id="e9", conf=0.3),  # unsure -> escalate
        ans("c", checks={"subgoal_complete": 0.9}),  # control signal -> no action, wrong
        ans("d", label="STUCK", element_id=None, verb=None),  # -> escalate
    ]
    llm = [ans(u, decider="gpt-6-luna", latency=2000, cost=0.0004) for u in "abcd"]
    outcomes = escalate_outcomes(jev, llm, Policy(threshold=0.6))
    assert [o.escalated for o in outcomes] == [False, True, False, True]
    row = row_from_outcomes("clev", outcomes, prepared)
    assert row.element_acc == 0.75 and row.escalation_rate == 0.5
    assert row.cost_per_step == pytest.approx((0.0002 * 4 + 0.0004 * 2) / 4)
    jev_row = row_from_outcomes("jev", plain(jev), prepared)
    assert jev_row.element_acc == 0.5  # a, c (c's action counts when run alone)


def test_calibration_ece():
    prepared = [prep(str(i)) for i in range(10)]
    # Confidence 0.95 but only half right: badly calibrated.
    jev = [ans(str(i), conf=0.95, element_id="e1" if i % 2 else "e2") for i in range(10)]
    bins, ece = calibration(jev, prepared)
    assert len(bins) == 1 and bins[0].accuracy == 0.5
    assert ece == pytest.approx(0.45)


def test_write_report(tmp_path):
    prepared = [prep(u) for u in "abcd"]
    results = {
        ("jev", 200): [ans(u, conf=0.5 + 0.1 * i) for i, u in enumerate("abcd")],
        ("jev", 50): [ans(u) for u in "abcd"],
        ("gpt-6-luna", 200): [ans(u, decider="gpt-6-luna", latency=2000) for u in "abcd"],
    }
    summary = write_report(tmp_path, prepared, results, "gpt-6-luna", Policy())
    report = (tmp_path / "report.md").read_text()
    assert "**Clev** (Jev + gpt-6-luna @ 0.6)" in report
    assert "## Jev by option count" in report and "Calibration" in report
    assert (tmp_path / "reliability.png").stat().st_size > 1000
    assert (tmp_path / "threshold_sweep.png").stat().st_size > 1000
    assert len(summary["sweep"]) == 21


async def test_plan_subgoal_uses_live_replan_and_counts_cost():
    from evals.mind2web.planned import plan_subgoal
    from tests.fakes import FakeLLM

    p = prep("a")
    p.obs = Observation(app="a", title="budget", url="https://budget.example/")
    llm = FakeLLM(
        lambda *_: {"subgoals": ["Click the Budget Truck link", "Enter zip"]}, cost=0.0003
    )
    plan = await plan_subgoal(llm, "gpt-6-luna", p)
    assert plan.subgoal == "Click the Budget Truck link"
    assert plan.decider == "plan:gpt-6-luna" and plan.cost_usd == pytest.approx(0.0003)
    assert "TASK: task" in llm.calls[0]["user"]


def test_report_includes_planned_section(tmp_path):
    prepared = [prep(u) for u in "abcd"]
    results = {
        ("jev", 200): [ans(u) for u in "abcd"],
        ("gpt-6-luna", 200): [ans(u, decider="gpt-6-luna") for u in "abcd"],
    }
    plans = [
        Answer(u, "plan:gpt-6-luna", 0, latency_ms=1500, cost_usd=0.0001, subgoal=f"Click {u}")
        for u in "abcd"
    ]
    planned = {
        "jev+plan": [ans(u) for u in "abcd"],
        "gpt-6-luna+plan": [ans(u, decider="gpt-6-luna", element_id="e9") for u in "abcd"],
    }
    summary = write_report(
        tmp_path, prepared, results, "gpt-6-luna", Policy(), planned=(plans, planned)
    )
    report = (tmp_path / "report.md").read_text()
    assert "## Live-style: planner writes the next subgoal" in report
    assert report.index("Live-style") < report.index("Pipeline ceiling")
    rows = {r["name"]: r for r in summary["planned"]}
    assert rows["jev + planner"]["element_acc"] == 1.0
    assert rows["gpt-6-luna + planner"]["element_acc"] == 0.0
    assert rows["jev + planner"]["latency_median_ms"] == 2000  # 500 decide + 1500 plan


@pytest.mark.parametrize(
    ("repr_", "sentence"),
    [
        ("[textbox]  US City,State or Zip Code -> TYPE: 08817",
         'Typed "08817" into textbox "US City,State or Zip Code"'),
        ("[link]  Budget Truck -> CLICK", 'Clicked link "Budget Truck"'),
        ("[select]  Select Pick-up Time -> SELECT: 02:30 PM",
         'Selected "02:30 PM" in select "Select Pick-up Time"'),
        ("[button]  Reservations -> HOVER", 'Hovered over button "Reservations"'),
        ("[input]   -> CLICK", "Clicked input"),
        ("garbage", "garbage"),
    ],
)  # fmt: skip
def test_history_reads_as_sentences(repr_, sentence):
    from evals.mind2web.loader import repr_to_sentence

    assert repr_to_sentence(repr_) == sentence


def test_last_target():
    s = step("a")
    assert s.last_target is None
    s.previous = ["[link]  Trucks -> CLICK", "[textbox]  Zip Code -> TYPE: 1"]
    assert s.last_target == "Zip Code"
    assert s.history[-1] == 'Typed "1" into textbox "Zip Code"'


def test_cache_key_includes_input_hash():
    from evals.mind2web.run import input_hash

    a = ans("a")
    a.input_hash = input_hash("state text")
    assert a.key.endswith("|" + input_hash("state text"))
    assert input_hash("state text") != input_hash("other text")
