"""Match elements across observations (ids are only stable within one observation)."""

from __future__ import annotations

from clev.core.types import Element, Observation


def find_same(obs: Observation, old: Element) -> Element | None:
    """Find `old` in a newer observation.

    Widgets change role when activated (Wikipedia's searchbox becomes a combobox on focus), so
    match by name, preferring the focused element and then the same role, else the focused one.
    """
    same_name = [e for e in obs.elements if e.name == old.name]
    for e in same_name:
        if e.focused:
            return e
    for e in same_name:
        if e.role == old.role:
            return e
    return next((e for e in obs.elements if e.focused), same_name[0] if same_name else None)
