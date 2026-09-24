import pytest

from clev.core.errors import ActionError, StaleElementError
from clev.core.types import Action
from clev.execute.browser import BrowserExecutor, to_playwright_key
from clev.observe.browser import BrowserObserver


def by_name(obs, name):
    return next(e for e in obs.elements if e.name == name)


@pytest.fixture
def agent(browser_session):
    observer = BrowserObserver(browser_session)
    executor = BrowserExecutor(browser_session, action_timeout_ms=1000, settle_ms=0, wait_ms=50)
    return observer, executor


async def js(browser_session, expr):
    return await browser_session.page.evaluate(expr)


async def test_click(browser_session, open_page, agent):
    observer, executor = agent
    await open_page('<button onclick="window.n = (window.n || 0) + 1">Add</button>')
    obs = await observer.observe()
    await executor.execute(Action(kind="click", element_id=by_name(obs, "Add").id), obs)
    assert await js(browser_session, "window.n") == 1


async def test_type_replaces_existing_value(browser_session, open_page, agent):
    observer, executor = agent
    await open_page('<input aria-label="City" value="Lahore">')
    obs = await observer.observe()
    city = by_name(obs, "City").id
    await executor.execute(Action(kind="type", element_id=city, text="Muscat"), obs)
    assert await js(browser_session, "document.querySelector('input').value") == "Muscat"


async def test_type_into_contenteditable(browser_session, open_page, agent):
    observer, executor = agent
    await open_page('<div contenteditable="true" aria-label="Body">old</div>')
    obs = await observer.observe()
    await executor.execute(Action(kind="type", element_id=by_name(obs, "Body").id, text="new"), obs)
    assert await js(browser_session, "document.querySelector('div').innerText") == "new"


async def test_key_on_element_and_page(browser_session, open_page, agent):
    observer, executor = agent
    await open_page(
        """<input aria-label="Q">
        <script>
          window.keys = [];
          addEventListener('keydown', e => {
            if (e.key !== 'Meta') keys.push((e.metaKey ? 'Meta+' : '') + e.key);
          });
        </script>"""
    )
    obs = await observer.observe()
    await executor.execute(Action(kind="key", element_id=by_name(obs, "Q").id, key="enter"), obs)
    await executor.execute(Action(kind="key", key="cmd+k"), obs)
    assert await js(browser_session, "window.keys") == ["Enter", "Meta+k"]


async def test_scroll(browser_session, open_page, agent):
    observer, executor = agent
    await open_page('<div style="height:5000px">tall</div>')
    obs = await observer.observe()
    await executor.execute(Action(kind="scroll", direction="down"), obs)
    down = await js(browser_session, "scrollY")
    assert down > 0
    await executor.execute(Action(kind="scroll", direction="up"), obs)
    assert await js(browser_session, "scrollY") < down


async def test_back(browser_session, site, agent):
    observer, executor = agent
    first = site.add("a.html", '<a href="b.html">Next</a>', title="A")
    site.add("b.html", "<h1>B</h1>", title="B")
    await browser_session.goto(first)
    obs = await observer.observe()
    await executor.execute(Action(kind="click", element_id=by_name(obs, "Next").id), obs)
    assert await browser_session.page.title() == "B"
    await executor.execute(Action(kind="back"), await observer.observe())
    assert await browser_session.page.title() == "A"


async def test_new_tab_becomes_current_page(browser_session, site):
    observer = BrowserObserver(browser_session)
    executor = BrowserExecutor(browser_session, settle_ms=300)  # default settle catches new tabs
    site.add("other.html", "<h1>Other</h1>", title="Other")
    home = site.add("home.html", '<a href="other.html" target="_blank">Pop</a>')
    await browser_session.goto(home)
    obs = await observer.observe()
    await executor.execute(Action(kind="click", element_id=by_name(obs, "Pop").id), obs)
    assert await browser_session.page.title() == "Other"


async def test_stale_ids_are_rejected(browser_session, open_page, agent):
    observer, executor = agent
    await open_page("<button>Go</button>")
    old = await observer.observe()
    await observer.observe()  # a newer observation replaces the id map
    with pytest.raises(StaleElementError):
        await executor.execute(Action(kind="click", element_id="e0"), old)

    fresh = await observer.observe()
    await open_page("<button>Other page</button>")  # navigation drops the id map
    with pytest.raises(StaleElementError):
        await executor.execute(Action(kind="click", element_id="e0"), fresh)


async def test_bad_actions_raise_action_error(browser_session, open_page, agent):
    observer, executor = agent
    await open_page("<button disabled>Nope</button><input aria-label='F'>")
    obs = await observer.observe()
    with pytest.raises(ActionError):
        await executor.execute(Action(kind="click", element_id=by_name(obs, "Nope").id), obs)
    with pytest.raises(ActionError):
        await executor.execute(Action(kind="type", element_id=by_name(obs, "F").id), obs)
    with pytest.raises(ActionError):
        await executor.execute(Action(kind="click"), obs)


async def test_wait_done_fail_are_safe(browser_session, open_page, agent):
    observer, executor = agent
    await open_page("<p>hi</p>")
    obs = await observer.observe()
    for kind in ("wait", "done", "fail"):
        await executor.execute(Action(kind=kind), obs)


@pytest.mark.parametrize(
    ("clev", "playwright"),
    [("cmd+enter", "Meta+Enter"), ("ctrl+shift+t", "Control+Shift+t"), ("esc", "Escape"),
     ("f5", "F5"), ("a", "a"), ("ArrowDown", "ArrowDown"), ("Option+Tab", "Alt+Tab")],
)  # fmt: skip
def test_key_mapping(clev, playwright):
    assert to_playwright_key(clev) == playwright


def test_empty_key_rejected():
    with pytest.raises(ActionError):
        to_playwright_key(" + ")
