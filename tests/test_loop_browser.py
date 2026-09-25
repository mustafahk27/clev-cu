"""End-to-end loop in real Chromium on a local fake site (no network, no models)."""

from clev.config import Settings
from clev.core.loop import Agent
from clev.decide.mock import MockDecider
from clev.execute.browser import BrowserExecutor
from clev.observe.browser import BrowserObserver
from clev.safety.gate import SafetyGate
from tests.fakes import FakePlanner, FakeTracer

HOME = """<header><form action="results.html" role="search">
  <input type="search" name="q" aria-label="Search the wiki"><button>Search</button>
</form></header><main><h1>Welcome</h1><a href="about.html">About</a></main>"""
RESULTS = """<main><h1>Search results</h1>
  <a href="muscat.html">Muscat</a><a href="oman.html">Oman</a></main>"""
ARTICLE = "<main><h1>Muscat</h1><p>Capital of Oman.</p></main>"


async def test_agent_searches_and_opens_article_in_a_real_browser(browser_session, site):
    home = site.add("home.html", HOME, title="Wiki")
    site.add("results.html", RESULTS, title="Results")
    site.add("muscat.html", ARTICLE, title="Muscat - Wiki")
    planner = FakePlanner(
        ['Type "Muscat" into the search box', "Press Enter to search", "Open the Muscat article"],
        start_url=home,
    )
    tracer = FakeTracer()
    agent = Agent(
        observer=BrowserObserver(browser_session),
        executor=BrowserExecutor(browser_session, settle_ms=50),
        decider=MockDecider(),
        planner=planner,
        gate=SafetyGate(allowed_domains=["clev.test"]),
        tracer=tracer,
        settings=Settings(_env_file=None),
        run_id="e2e",
    )
    result = await agent.run("search the wiki for Muscat and open the article")

    assert result.success, result.reason
    assert await browser_session.page.title() == "Muscat - Wiki"
    steps = [r for r in tracer.records if r.event == "step"]
    typed = steps[0].decision.action
    assert typed.kind == "type" and typed.text == "Muscat"
    assert all(r.error is None for r in steps)
