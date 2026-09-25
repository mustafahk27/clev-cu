import pytest

from clev.config import Settings
from clev.core.loop import Agent
from clev.decide.mock import MockDecider
from clev.safety.gate import SafetyGate
from tests.fakes import FakePlanner, FakeSite, FakeTracer, el

PLAN = ['Type "Muscat" into the search box', "Press Enter to search", "Open the Muscat article"]


def wiki_site() -> FakeSite:
    return FakeSite(
        {
            "home": [
                el("e0", "searchbox", "Search Wikipedia", editable=True),
                el("e1", "button", "Search"),
                el("e2", "link", "Log in"),
            ],
            "results": [el("e0", "link", "Muscat"), el("e1", "link", "Muscat Governorate")],
            "muscat": [el("e0", "heading", "Muscat"), el("e1", "link", "Oman")],
        },
        on_enter="results",
    )


def make_agent(site, planner, decider=None, gate=None, **settings):
    tracer = FakeTracer()
    agent = Agent(
        observer=site,
        executor=site,
        decider=decider or MockDecider(),
        planner=planner,
        gate=gate or SafetyGate(),
        tracer=tracer,
        settings=Settings(_env_file=None, **settings),
        run_id="t",
    )
    return agent, tracer


async def test_happy_path_completes_the_task():
    site = wiki_site()
    agent, tracer = make_agent(site, FakePlanner(PLAN))
    result = await agent.run("search Wikipedia for Muscat and open the article")

    assert result.success, result.reason
    assert site.page == "muscat"
    assert [a.kind for a in site.executed] == ["type", "key", "click"]
    assert site.executed[0].text == "Muscat"  # literal from the subgoal, no write_text call
    assert result.done == PLAN
    events = [r.event for r in tracer.records]
    assert events[0] == "plan" and events[-1] == "end"
    assert tracer.records[-1].note.startswith("success")
    # Type completes its subgoal directly; Enter and click each need a SUBGOAL_DONE step.
    assert result.steps == 5
    assert result.cost_usd == pytest.approx(0.01)  # one planner call; the mock decider is free


async def test_start_url_is_opened_through_the_gate():
    site = wiki_site()
    site.page = "blank"
    site.pages["blank"] = []
    agent, _ = make_agent(site, FakePlanner(PLAN, start_url="https://fake.test/home"))
    result = await agent.run("task")
    assert result.success
    assert site.executed[0].kind == "goto"


async def test_domain_allowlist_blocks_start_url():
    site = wiki_site()
    planner = FakePlanner(PLAN, start_url="https://evil.test/home")
    agent, _ = make_agent(site, planner, gate=SafetyGate(allowed_domains=["fake.test"]))
    result = await agent.run("task")
    assert not result.success and "ALLOWED_DOMAINS" in result.reason
    assert site.executed == []


async def test_trace_keeps_only_option_elements():
    site = wiki_site()
    site.pages["home"] += [el(f"x{i}", "button", f"Junk {i}", visible=False) for i in range(50)]
    agent, tracer = make_agent(site, FakePlanner(PLAN))
    await agent.run("task")
    step = next(r for r in tracer.records if r.event == "step")
    assert {e.id for e in step.observation.elements} == {"e0", "e1", "e2"}
    assert step.state_text.startswith("APP: fake")


async def test_none_of_these_triggers_replan_then_gives_up():
    site = wiki_site()
    planner = FakePlanner(["Open the settings panel"], replans=[["Open the preferences panel"]])
    agent, tracer = make_agent(site, planner, max_replans=1)
    result = await agent.run("task")
    assert not result.success
    assert "gave up after 1 replans" in result.reason
    assert "NONE_OF_THESE" in planner.replan_reasons[0]
    assert [r.event for r in tracer.records].count("replan") == 1


async def test_empty_replan_means_done():
    site = wiki_site()
    planner = FakePlanner(["Open the settings panel"], replans=[[]])
    agent, _ = make_agent(site, planner)
    result = await agent.run("task")
    assert result.success


async def test_step_cap():
    site = wiki_site()
    agent, _ = make_agent(site, FakePlanner(PLAN), max_steps=2)
    result = await agent.run("task")
    assert not result.success and "step cap (2)" in result.reason
    assert result.steps == 2


async def test_write_text_used_when_subgoal_has_no_literal():
    site = wiki_site()
    planner = FakePlanner(["Type a short greeting into the search box"], text="hello there")
    agent, _ = make_agent(site, planner)
    await agent.run("task")
    assert planner.write_calls == 1
    assert site.executed[0].text == "hello there"


async def test_repeated_failures_trigger_replan():
    site = wiki_site()
    site.fail_next = 10
    planner = FakePlanner(["Open the Log in page"], replans=[[]])
    agent, tracer = make_agent(site, planner)
    result = await agent.run("task")
    assert result.success  # the empty replan ends it
    assert "3 failed actions in a row" in planner.replan_reasons[0]
    assert sum(1 for r in tracer.records if r.error) == 3


async def test_dry_run_executes_nothing_and_walks_the_plan():
    # Nothing changes on screen in a dry run, so only subgoals for the current page can match.
    site = wiki_site()
    agent, tracer = make_agent(site, FakePlanner(PLAN[:2]), dry_run=True)
    result = await agent.run("task")
    assert result.success
    assert site.executed == []
    assert all(r.note == "dry run: not executed" for r in tracer.records if r.event == "step")


async def test_destructive_click_asks_and_declining_stops():
    asked = []

    async def deny(question):
        asked.append(question)
        return False

    site = FakeSite({"home": [el("e0", "button", "Delete account")]})
    agent, _ = make_agent(site, FakePlanner(["Click the Delete account button"]),
                          gate=SafetyGate(confirm=deny))  # fmt: skip
    result = await agent.run("task")
    assert not result.success and "user declined" in result.reason
    assert asked and "Delete account" in asked[0]
    assert site.executed == []


async def test_credential_field_is_never_typed():
    site = FakeSite({"home": [el("e0", "textbox", "Password", editable=True)]})
    agent, _ = make_agent(site, FakePlanner(['Type "hunter2" into the password field']))
    result = await agent.run("task")
    assert not result.success and "credential field" in result.reason
    assert site.executed == []


async def test_repeat_detection():
    site = FakeSite({"home": [el("e0", "button", "Load more")]})

    class ClickForever(MockDecider):
        async def decide(self, state, subgoal, history):
            d = await super().decide(state, subgoal, [])  # forgets it already acted
            return d

    planner = FakePlanner(["Click Load more"], replans=[[]])
    agent, _ = make_agent(site, planner, decider=ClickForever())
    result = await agent.run("task")
    assert result.success
    assert "repeated the same action 3 times" in planner.replan_reasons[0]
    assert len(site.executed) == 3
