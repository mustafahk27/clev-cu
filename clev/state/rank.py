"""Heuristic candidate ranking against the current subgoal (plan §7, v1)."""

from __future__ import annotations

from collections.abc import Sequence

from clev.core.types import Element
from clev.state.filter import in_dialog, in_viewport
from clev.state.goal import Goal, tokens

# Words a subgoal uses to describe a role ("the search box", "the dropdown").
ROLE_WORDS: dict[str, frozenset[str]] = {
    role: frozenset(tokens(words))
    for role, words in {
        "searchbox": "search box field input bar",
        "textbox": "field box input text area",
        "combobox": "dropdown select field box menu list",
        "checkbox": "checkbox check box tick",
        "radio": "radio option choice",
        "button": "button",
        "link": "link",
        "tab": "tab",
        "menuitem": "menu item",
        "option": "option choice",
        "switch": "toggle switch",
        "slider": "slider",
    }.items()
}
TYPE_ROLES = frozenset({"textbox", "searchbox"})

W_NAME = 2.0  # per goal word found in the element's name
W_PRECISION = 2.0  # x fraction of the name's words that are in the goal (penalizes long names)
W_PHRASE = 3.0  # the whole name appears in the goal
W_CONTEXT = 0.75  # per goal word found in the context path
W_ROLE = 1.0
W_FOCUSED = 1.0
W_DIALOG = 2.0
W_VIEWPORT = 0.5
W_EDITABLE = 1.5  # typing goal and the element takes text
P_NOT_EDITABLE = 4.0  # typing goal but the element can't take text (a link named "Search")
P_CHROME = 0.5  # navigation / footer regions


def is_editable(e: Element) -> bool:
    return e.editable or e.role in TYPE_ROLES


def score(
    e: Element,
    goal: Goal,
    viewport: tuple[int, int, int, int] | None = None,
    dialog_open: bool = False,
) -> float:
    name = set(tokens(e.name))
    s = 0.0
    if name and goal.tokens:
        hits = len(goal.tokens & name)
        s += W_NAME * hits + W_PRECISION * hits / len(name)
        phrase = " ".join(tokens(e.name))
        if len(phrase) >= 3 and f" {phrase} " in f" {goal.described} ":
            s += W_PHRASE
    s += W_CONTEXT * len(goal.tokens & set(tokens(e.context)))
    if goal.tokens & ROLE_WORDS.get(e.role, frozenset()):
        s += W_ROLE
    if goal.is_typing:
        s += W_EDITABLE if is_editable(e) else -P_NOT_EDITABLE
    if e.focused:
        s += W_FOCUSED
    if dialog_open:
        s += W_DIALOG if in_dialog(e) else -W_DIALOG
    if in_viewport(e, viewport):
        s += W_VIEWPORT
    if "navigation" in e.context or "contentinfo" in e.context:
        s -= P_CHROME
    return s


RESERVE_FRACTION = 0.2


def select(
    ranked: Sequence[Element],
    k: int,
    order: dict[str, int],
    reserve_fraction: float = RESERVE_FRACTION,
) -> list[Element]:
    """Pick `k` candidates in priority order: the best (1 - reserve) by rank, then reserve slots
    spread evenly across the rest of the page (always including its last element).

    A target that shares no words with the goal ("next page" vs a link named "More") scores low;
    without the reserve it's cut whenever it sits near the bottom of a long page.
    """
    if len(ranked) <= k:
        return list(ranked)
    n_top = k - int(k * reserve_fraction)
    top = list(ranked[:n_top])
    rest = sorted(ranked[n_top:], key=lambda e: order[e.id])  # page order
    n_reserve = k - n_top
    if n_reserve <= 0:
        return top
    step = (len(rest) - 1) / max(1, n_reserve - 1)
    picks = sorted({round(i * step) for i in range(n_reserve)}, reverse=True)  # bottom first
    return top + [rest[i] for i in picks]


# Context priors (tuned on the Mind2Web train split, never the test split). Each helps when the
# goal shares no words with the target: long task-level goals, generic "continue" steps.
# Chosen on 400 train steps (2026-10-01): top-50 recall 45.8% -> 51.0%, top-200 67.8% -> 69.0%,
# with subgoal-style labels unchanged or better. Larger weights overfit (labels @1 87% -> 74%).
W_NEAR = 3.0  # max bonus for candidates next to the element the last action touched
NEAR_WINDOW = 10  # candidates within this many positions (page order) of it get a share
W_FORM = 2.0  # fields that take text are frequent targets
W_ADVANCE = 0.5  # controls that move a flow forward
ADVANCE_WORDS = frozenset(
    tokens("search submit continue next go apply find done ok proceed show view results")
)


def anchor_index(candidates: Sequence[Element], anchor: str | None) -> int | None:
    """Position of the element the last action touched, matched by name (ids change)."""
    if not anchor:
        return None
    want = anchor.strip().lower()
    return next((i for i, e in enumerate(candidates) if e.name.strip().lower() == want), None)


def rank(
    candidates: Sequence[Element],
    subgoal: str,
    viewport: tuple[int, int, int, int] | None = None,
    anchor: str | None = None,
) -> list[tuple[Element, float]]:
    """Candidates with scores, best first. Ties keep page order.

    `anchor`: name of the element the previous action touched, if any.
    """
    goal = Goal.parse(subgoal)
    dialog_open = any(in_dialog(e) for e in candidates)
    at = anchor_index(candidates, anchor)
    scored = []
    for i, e in enumerate(candidates):
        s = score(e, goal, viewport, dialog_open)
        if at is not None and i != at and W_NEAR:
            s += W_NEAR * max(0.0, 1 - abs(i - at) / NEAR_WINDOW)
        if W_FORM and is_editable(e):
            s += W_FORM
        if W_ADVANCE and set(tokens(e.name)) & ADVANCE_WORDS:
            s += W_ADVANCE
        scored.append((e, s))
    return sorted(scored, key=lambda pair: -pair[1])  # sorted() is stable
