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


def rank(
    candidates: Sequence[Element],
    subgoal: str,
    viewport: tuple[int, int, int, int] | None = None,
) -> list[tuple[Element, float]]:
    """Candidates with scores, best first. Ties keep page order."""
    goal = Goal.parse(subgoal)
    dialog_open = any(in_dialog(e) for e in candidates)
    scored = [(e, score(e, goal, viewport, dialog_open)) for e in candidates]
    return sorted(scored, key=lambda pair: -pair[1])  # sorted() is stable
