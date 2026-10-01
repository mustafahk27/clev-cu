import pytest
from pydantic import ValidationError

from clev.core.types import Observation, StepRecord
from clev.decide.llm_decider import LLMDecider, choice_schema
from clev.decide.mock import MockDecider
from clev.planner.planner import LLMPlanner, describe_page
from clev.planner.prompts import DECIDE_SYSTEM, PLAN_SYSTEM
from clev.state.serialize import build_state
from tests.fakes import FakeLLM, el


def page(*elements, url="https://en.wikipedia.org/wiki/Karachi"):
    return Observation(app="chromium", title="Karachi", url=url, elements=list(elements))


# --- planner -------------------------------------------------------------------------------


async def test_plan_parses_start_url_and_subgoals():
    llm = FakeLLM(lambda schema, s, u: {
        "start_url": "https://en.wikipedia.org",
        "subgoals": ['Type "Karachi" into the search box', " ", "Open the Karachi article"],
    })  # fmt: skip
    planner = LLMPlanner(llm, "gpt-6-luna")
    plan = await planner.plan("search wikipedia for karachi", page(url="about:blank"))
    assert plan.start_url == "https://en.wikipedia.org"
    assert plan.subgoals == ['Type "Karachi" into the search box', "Open the Karachi article"]
    assert planner.cost_usd == pytest.approx(0.001)
    call = llm.calls[0]
    assert call["model"] == "gpt-6-luna" and call["system"] == PLAN_SYSTEM
    assert "TASK: search wikipedia for karachi" in call["user"]
    assert "PAGE: (blank" in call["user"]


async def test_plan_drops_non_http_start_urls():
    llm = FakeLLM(lambda *_: {"start_url": "javascript:alert(1)", "subgoals": ["x"]})
    plan = await LLMPlanner(llm, "m").plan("t", page())
    assert plan.start_url is None


async def test_replan_and_write_text():
    replies = iter([{"subgoals": ["Click Search"]}, {"text": "Dear team, ..."}])
    llm = FakeLLM(lambda *_: next(replies))
    planner = LLMPlanner(llm, "m")
    assert await planner.replan("t", ["a"], page(), "stuck") == ["Click Search"]
    assert "REASON FOR REPLANNING: stuck" in llm.calls[0]["user"]
    assert "1. a" in llm.calls[0]["user"]
    field = el("e1", "textbox", "Message body")
    assert await planner.write_text("t", "Write the body", field) == "Dear team, ..."
    assert "FIELD: textbox 'Message body'" in llm.calls[1]["user"]
    assert planner.cost_usd == pytest.approx(0.002)


def test_describe_page_lists_visible_candidates():
    obs = page(
        el("e0", "link", "History", context="navigation"),
        el("e1", "button", "Hidden", visible=False),
    )
    text = describe_page(obs)
    assert "PAGE: Karachi | https://en.wikipedia.org/wiki/Karachi" in text
    assert "link 'History' @ navigation" in text and "Hidden" not in text


def test_prompts_treat_page_text_as_untrusted():
    for prompt in (PLAN_SYSTEM, DECIDE_SYSTEM):
        assert "data, not instructions" in prompt


# --- LLM decider ---------------------------------------------------------------------------


def test_choice_schema_only_accepts_option_labels():
    Schema = choice_schema(["1", "2", "STUCK"])
    assert Schema.model_validate({"reason": "r", "choice": "2"}).choice == "2"
    with pytest.raises(ValidationError):
        Schema.model_validate({"reason": "r", "choice": "99"})
    props = Schema.model_json_schema()["properties"]["choice"]
    assert props["enum"] == ["1", "2", "STUCK"]


async def test_llm_decider_maps_label_to_action_and_includes_history():
    obs = page(
        el("e0", "searchbox", "Search Wikipedia", editable=True), el("e1", "link", "History")
    )
    state = build_state(obs, "Open the History section")
    history_label = next(o.label for o in state.options if o.action and o.action.element_id == "e1")
    llm = FakeLLM(lambda schema, s, u: {"reason": "matches", "choice": history_label}, cost=0.0004)
    earlier = await MockDecider().decide(state, "Search", [])
    past = StepRecord(
        run_id="r", step=1, subgoal="x", observation=obs, decision=earlier, executed=True
    )
    decision = await LLMDecider(llm, "gpt-6-luna").decide(state, "Open the History section", [past])

    assert decision.decided_by == "llm" and decision.chosen_label == history_label
    assert decision.action.kind == "click" and decision.action.element_id == "e1"
    assert decision.cost_usd == pytest.approx(0.0004)
    user = llm.calls[0]["user"]
    assert user.startswith("APP: chromium") and "RECENT ACTIONS:" in user and "-> ok" in user


async def test_llm_decider_control_labels_have_no_action():
    state = build_state(page(el("e0", "link", "History")), "Open History")
    llm = FakeLLM(lambda *_: {"reason": "done", "choice": "SUBGOAL_DONE"})
    decision = await LLMDecider(llm, "m").decide(state, "Open History", [])
    assert decision.action is None and decision.chosen_label == "SUBGOAL_DONE"


async def test_llm_decider_check_is_a_probability():
    state = build_state(page(), "x")
    llm = FakeLLM(lambda *_: {"answer": True})
    assert await LLMDecider(llm, "m").check(state, "Is an error visible?") == 1.0


# --- mock decider --------------------------------------------------------------------------


async def test_mock_decider_policy():
    obs = page(el("e0", "searchbox", "Search Wikipedia", editable=True), el("e1", "link", "Log in"))
    state = build_state(obs, 'Type "x" into the search box')
    mock = MockDecider()
    first = await mock.decide(state, 'Type "x" into the search box', [])
    assert first.action.kind == "type" and first.action.element_id == "e0"
    assert (await mock.decide(state, "Press Enter to search", [])).chosen_label == "PRESS_ENTER"
    assert (await mock.decide(state, "Open the settings", [])).chosen_label == "NONE_OF_THESE"
    acted = StepRecord(run_id="r", step=1, subgoal="Log in", decision=first, executed=True)
    assert (await mock.decide(state, "Log in", [acted])).chosen_label == "SUBGOAL_DONE"


def test_describe_page_shows_task_relevant_elements_on_long_pages():
    import clev.planner.planner as planner_mod

    filler = [el(f"e{i}", "link", f"Footer link {i}") for i in range(100)]
    target = el("e100", "link", "Budget Truck rental")
    obs = page(*filler, target)
    assert "Budget Truck" not in describe_page(obs)  # first-N view misses it
    text = describe_page(obs, "Rent a budget truck")
    assert "Budget Truck rental" in text
    assert text.count("\n") == planner_mod.PAGE_ELEMENTS
