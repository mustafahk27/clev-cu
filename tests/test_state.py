from functools import cache
from pathlib import Path

import pytest

from clev.core.types import Element, Observation
from clev.observe.io import load_observation
from clev.state.filter import MAX_CONTEXT, filter_elements, in_viewport
from clev.state.goal import Goal, extract_literal, tokens
from clev.state.rank import rank, select
from clev.state.serialize import GLOBAL_OPTIONS, build_state
from tests.state_labels import HELDOUT, LABELS

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_NAMES = sorted({name for name, _, _ in LABELS + HELDOUT})
GLOBAL_LABELS = [label for label, _, _ in GLOBAL_OPTIONS]


@cache
def fixture(name: str) -> Observation:
    return load_observation(FIXTURES / f"{name}.json.gz")


def el(id, role="button", name="", context="", **kw) -> Element:
    return Element(id=id, role=role, name=name, context=context, **kw)


# --- Phase 3 "done when" -------------------------------------------------------------------


def target_rank(name: str, subgoal: str, target) -> int | None:
    obs = fixture(name)
    ranked = rank(filter_elements(obs).candidates, subgoal, obs.viewport)
    return next((i for i, (e, _) in enumerate(ranked, 1) if target.matches(e)), None)


def test_labels_have_20_steps_and_all_targets_exist():
    assert len(LABELS) >= 20
    for name, subgoal, target in LABELS:
        assert any(target.matches(e) for e in fixture(name).elements), (name, subgoal)


def test_target_recall_in_top_200_is_at_least_95_percent():
    ranks = [target_rank(*label) for label in LABELS]
    misses = [label[1] for label, r in zip(LABELS, ranks, strict=True) if r is None or r > 200]
    assert 1 - len(misses) / len(LABELS) >= 0.95, misses


def options_contain(name: str, subgoal: str, target) -> bool:
    obs = fixture(name)
    state = build_state(obs, subgoal)
    return any(
        o.action and o.action.element_id and target.matches(obs.element(o.action.element_id))
        for o in state.options
    )


def test_heldout_recall_in_serialized_options():
    # Pages and goals the ranker was never tuned on (see HELDOUT). 18/18 after the recall fix.
    for name, subgoal, target in HELDOUT:
        assert any(target.matches(e) for e in fixture(name).elements), (name, subgoal)
    hits = [options_contain(*label) for label in HELDOUT]
    misses = [label[1] for label, ok in zip(HELDOUT, hits, strict=True) if not ok]
    assert 1 - len(misses) / len(HELDOUT) >= 0.95, misses


def test_target_recall_in_top_10_regression_guard():
    # Not a plan requirement: guards the heuristic against regressions (currently 100%).
    ranks = [target_rank(*label) for label in LABELS]
    assert sum(1 for r in ranks if r and r <= 10) / len(LABELS) >= 0.9


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_serialized_fixture_fits_budget_and_is_well_formed(name):
    obs = fixture(name)
    state = build_state(obs, "Open the first link", ["Opened the page"])
    assert state.token_estimate <= 24000
    labels = [o.label for o in state.options]
    assert len(labels) == len(set(labels))
    assert labels[-len(GLOBAL_LABELS) :] == GLOBAL_LABELS
    element_options = state.options[: -len(GLOBAL_LABELS)]
    assert 0 < len(element_options) <= 200
    assert [o.label for o in element_options] == [
        str(i) for i in range(1, len(element_options) + 1)
    ]
    for o in element_options:
        e = obs.element(o.action.element_id)
        assert e is not None and e.visible and e.enabled
        assert o.action.kind == (
            "type" if e.editable or e.role in ("textbox", "searchbox") else "click"
        )
    lines = state.text.splitlines()
    assert lines[0].startswith("APP: chromium | TITLE: ")
    assert lines[1] == "GOAL: Open the first link"
    assert lines[2] == "DONE SO FAR: 1) Opened the page"
    assert "OPTIONS:" in lines


# --- Serializer budget ---------------------------------------------------------------------


def big_obs(n: int, name_len: int = 150) -> Observation:
    return Observation(
        app="chromium",
        title="Big",
        elements=[el(f"e{i}", "link", f"item {i} " + "x" * name_len) for i in range(n)],
    )


def test_over_budget_truncates_names_then_drops_worst_options():
    obs = big_obs(200)
    roomy = build_state(obs, "open item 7", token_budget=100_000)
    assert len(roomy.options) == 200 + len(GLOBAL_LABELS)

    tight = build_state(obs, "open item 7", token_budget=3000)
    assert tight.token_estimate <= 3000
    assert len(tight.options) < len(roomy.options)
    assert "…" in tight.options[0].line  # names were clipped
    kept = {o.action.element_id for o in tight.options if o.action and o.action.element_id}
    assert "e7" in kept  # the best match survives the cut
    assert [o.label for o in tight.options][-len(GLOBAL_LABELS) :] == GLOBAL_LABELS


def test_max_options_caps_candidates():
    state = build_state(big_obs(300, 5), "open item 1", max_options=50)
    assert len(state.options) == 50 + len(GLOBAL_LABELS)


def test_impossible_budget_still_returns_global_options():
    state = build_state(big_obs(20), "anything", token_budget=10)
    assert [o.label for o in state.options] == GLOBAL_LABELS


def test_options_are_in_page_order_and_global_actions_map():
    obs = Observation(
        app="chromium",
        title="t",
        elements=[el("e0", "link", "Alpha"), el("e1", "link", "Beta"), el("e2", "link", "Gamma")],
    )
    state = build_state(obs, "open Gamma")
    assert [o.action.element_id for o in state.options[:3]] == ["e0", "e1", "e2"]
    by_label = {o.label: o.action for o in state.options}
    assert by_label["SCROLL_DOWN"].direction == "down"
    assert by_label["GO_BACK"].kind == "back"
    assert by_label["STUCK"] is None and by_label["SUBGOAL_DONE"] is None


# --- Filter --------------------------------------------------------------------------------


def test_filter_keeps_visible_enabled_interactive_only():
    obs = Observation(
        app="a",
        title="t",
        elements=[
            el("e0", "button", "Ok"),
            el("e1", "button", "Hidden", visible=False),
            el("e2", "button", "Off", enabled=False),
            el("e3", "heading", "Title"),
            el("e4", "article", "Card"),
        ],
    )
    f = filter_elements(obs)
    assert [e.id for e in f.candidates] == ["e0"]
    assert [e.id for e in f.context] == ["e3"]


def test_context_prefers_alerts_then_on_screen_headings_and_caps():
    elements = [el(f"h{i}", "heading", f"Far {i}", bounds=(0, 5000 + i, 10, 10)) for i in range(40)]
    elements += [el("near", "heading", "Near", bounds=(0, 10, 10, 10))]
    elements += [el("err", "alert", "Card declined", bounds=(0, 9000, 10, 10))]
    obs = Observation(app="a", title="t", elements=elements, viewport=(0, 0, 1280, 800))
    ids = [e.id for e in filter_elements(obs).context]
    assert len(ids) == MAX_CONTEXT
    assert "err" in ids and "near" in ids
    assert "h39" not in ids


def test_in_viewport():
    vp = (0, 1000, 1280, 800)
    assert in_viewport(el("a", bounds=(10, 1200, 50, 20)), vp)
    assert not in_viewport(el("b", bounds=(10, 100, 50, 20)), vp)
    assert in_viewport(el("c"), vp)  # unknown bounds count as visible


# --- Goal parsing and ranking --------------------------------------------------------------


def test_goal_parsing():
    g = Goal.parse('Type "Muscat" into the destination field')
    assert g.is_typing and g.literal == "Muscat"
    assert "muscat" not in g.tokens and {"destination", "field"} <= g.tokens
    click = Goal.parse('Click the "Sign in" button')
    assert not click.is_typing and {"login", "button"} <= click.tokens  # "sign in" -> login
    assert "click" not in click.tokens
    assert extract_literal("Search for “Karachi port”") == "Karachi port"
    assert extract_literal("Open settings") is None


def test_rank_prefers_editable_for_typing_and_names_for_clicks():
    cands = [
        el("e0", "link", "Search"),
        el("e1", "searchbox", "Search Wikipedia", editable=True),
        el("e2", "link", "Muscat"),
    ]
    assert rank(cands, 'Type "Muscat" into the search box')[0][0].id == "e1"
    assert rank(cands, "Open the Muscat article")[0][0].id == "e2"


def test_rank_bonuses_and_penalties():
    dialog = [el("e0", "button", "OK"), el("e1", "button", "OK", context='dialog "Confirm"')]
    assert rank(dialog, "press OK")[0][0].id == "e1"
    focus = [el("e0", "textbox", "Name"), el("e1", "textbox", "Name", focused=True)]
    assert rank(focus, 'Type "x" into Name')[0][0].id == "e1"
    nav = [el("e0", "link", "Docs", context="navigation"), el("e1", "link", "Docs", context="main")]
    assert rank(nav, "open Docs")[0][0].id == "e1"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Log in to the site", "login"),
        ("Sign in", "Log in"),
        ("sign-out", "Log out"),
        ("Sign up", "Register"),
        ("Go to the next page", "More"),
        ("next", "»"),
        ("Enter the email", "name@example.com"),
        ("newest stories", "new"),
        ("Add to basket", "cart"),
    ],
)
def test_wording_normalization_meets_on_one_concept(a, b):
    assert set(tokens(a)) & set(tokens(b)), (tokens(a), tokens(b))


def test_non_plurals_are_not_stemmed():
    assert tokens("Hacker News") == ["hacker", "news"]
    assert "new" not in tokens("Hacker News")


def test_select_reserves_slots_across_the_page():
    ranked = [el(f"e{i}", "link", f"item {i}") for i in range(100)]
    order = {e.id: i for i, e in enumerate(ranked)}
    picked = select(ranked, 20, order)
    assert len(picked) == len({e.id for e in picked}) == 20
    assert [e.id for e in picked[:16]] == [f"e{i}" for i in range(16)]  # best 80% by rank
    reserve = {order[e.id] for e in picked[16:]}
    assert 99 in reserve  # the page's last element always makes it
    assert min(reserve) < 40 < max(reserve)  # spread, not bunched
    assert select(ranked[:10], 20, order) == ranked[:10]


def test_bottom_of_page_target_survives_a_long_page():
    elements = [el(f"e{i}", "link", f"Story {i}") for i in range(300)]
    elements.append(el("more", "link", "Zzz"))  # shares no words with the goal
    obs = Observation(app="a", title="t", elements=elements)
    state = build_state(obs, "Open the first story")
    assert "more" in {o.action.element_id for o in state.options if o.action}
