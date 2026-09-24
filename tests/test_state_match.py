from clev.core.types import Element, Observation
from clev.state.match import find_same


def el(id, role, name, focused=False):
    return Element(id=id, role=role, name=name, focused=focused)


def test_find_same_follows_role_change_and_focus():
    old = el("e18", "searchbox", "Search Wikipedia")
    # The searchbox became a focused combobox with the same name.
    new = Observation(app="a", title="t", elements=[
        el("e1", "link", "Search"),
        el("e18", "combobox", "Search Wikipedia", focused=True),
    ])  # fmt: skip
    assert find_same(new, old).id == "e18"
    # Same name, nothing focused: prefer the same role.
    new = Observation(app="a", title="t", elements=[
        el("e2", "heading", "Search Wikipedia"),
        el("e3", "searchbox", "Search Wikipedia"),
    ])  # fmt: skip
    assert find_same(new, old).id == "e3"
    # Name changed: fall back to whatever is focused.
    new = Observation(app="a", title="t", elements=[el("e4", "textbox", "Query", focused=True)])
    assert find_same(new, old).id == "e4"
    assert find_same(Observation(app="a", title="t"), old) is None
