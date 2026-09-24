"""Checks on observations captured from real sites (scripts/capture_fixtures.py)."""

from pathlib import Path

import pytest

from clev.observe.io import load_observation, save_observation

FIXTURES = Path(__file__).parent / "fixtures"

# name -> (min elements, an element that must be present as (role, name substring))
EXPECTED = {
    "wikipedia": (1000, ("searchbox", "Search Wikipedia")),
    "github": (100, ("link", "Issues")),
    "shop": (50, ("link", "Books")),
    "form": (20, ("textbox", "First Name")),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_is_valid_and_realistic(name):
    obs = load_observation(FIXTURES / f"{name}.json.gz")
    min_elements, (role, needle) = EXPECTED[name]

    assert obs.app == "chromium" and obs.url.startswith("https://")
    assert len(obs.elements) >= min_elements
    assert len({e.id for e in obs.elements}) == len(obs.elements)
    assert any(e.role == role and needle in e.name for e in obs.elements), (role, needle)
    assert any(e.visible for e in obs.elements)
    assert all(e.bounds is not None for e in obs.elements)


def test_fixtures_never_contain_secret_values():
    for path in FIXTURES.glob("*.json.gz"):
        for e in load_observation(path).elements:
            if e.value and "password" in (e.name + e.role).lower():
                assert e.value == "[redacted]", (path.name, e)


def test_save_load_roundtrip(tmp_path):
    obs = load_observation(FIXTURES / "form.json.gz")
    for suffix in (".json", ".json.gz"):
        save_observation(obs, tmp_path / f"o{suffix}")
        assert load_observation(tmp_path / f"o{suffix}") == obs


@pytest.mark.live
async def test_live_wikipedia_observe_and_click(browser_session):
    """Phase 2 'done when': observe a real page, list elements, click one by id."""
    from clev.core.types import Action
    from clev.execute.browser import BrowserExecutor
    from clev.observe.browser import BrowserObserver

    await browser_session.goto("https://en.wikipedia.org/wiki/Karachi")
    observer = BrowserObserver(browser_session)
    obs = await observer.observe()
    history = next(e for e in obs.elements if e.role == "link" and e.name == "History")
    await BrowserExecutor(browser_session).execute(Action(kind="click", element_id=history.id), obs)
    assert browser_session.page.url.endswith("#History")
