"""Filter an Observation down to actionable candidates plus a little on-screen context."""

from __future__ import annotations

from dataclasses import dataclass

from clev.core.types import Element, Observation

# Plan §7 allowlist, plus the other interactive ARIA roles the observers emit.
INTERACTIVE_ROLES = frozenset(
    {
        "button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio", "menuitem",
        "tab", "option", "switch", "slider",
        "menuitemcheckbox", "menuitemradio", "spinbutton", "listbox", "treeitem",
    }
)  # fmt: skip
CONTEXT_ROLES = frozenset({"heading", "alert", "status"})
MAX_CONTEXT = 30


@dataclass
class Filtered:
    candidates: list[Element]  # visible, enabled, interactive; DOM order
    context: list[Element]  # up to MAX_CONTEXT headings/alerts; DOM order


def in_viewport(e: Element, viewport: tuple[int, int, int, int] | None) -> bool:
    if viewport is None or e.bounds is None:
        return True  # unknown: don't penalize
    vx, vy, vw, vh = viewport
    x, y, w, h = e.bounds
    return x < vx + vw and x + w > vx and y < vy + vh and y + h > vy


def in_dialog(e: Element) -> bool:
    return "dialog" in e.context  # also matches alertdialog


def filter_elements(obs: Observation, max_context: int = MAX_CONTEXT) -> Filtered:
    candidates = [
        e for e in obs.elements if e.visible and e.enabled and e.role in INTERACTIVE_ROLES
    ]
    texts = [e for e in obs.elements if e.visible and e.role in CONTEXT_ROLES and e.name]
    dialog_open = any(in_dialog(e) for e in candidates)

    # Priority: alerts/status (errors, confirmations), then headings in an open dialog, then
    # headings on screen, then the rest in page order.
    def priority(e: Element) -> int:
        if e.role != "heading":
            return 0
        if dialog_open and in_dialog(e):
            return 1
        return 2 if in_viewport(e, obs.viewport) else 3

    chosen: list[Element] = []
    seen: set[str] = set()
    for e in sorted(texts, key=priority):  # stable: page order within a priority
        if e.name not in seen:
            seen.add(e.name)
            chosen.append(e)
        if len(chosen) >= max_context:
            break
    order = {e.id: i for i, e in enumerate(obs.elements)}
    return Filtered(candidates=candidates, context=sorted(chosen, key=lambda e: order[e.id]))
