import json

from typer.testing import CliRunner

from clev.cli import app, find_same
from clev.core.types import Element, Observation

runner = CliRunner()


def test_run_prints_parsed_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECIDER", raising=False)
    result = runner.invoke(app, ["run", "open wikipedia", "--mode", "browser", "--decider", "mock"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["task"] == "open wikipedia"
    assert payload["mode"] == "browser"
    assert payload["config"]["decider"] == "mock"


def test_run_rejects_bad_mode():
    result = runner.invoke(app, ["run", "x", "--mode", "windows"])
    assert result.exit_code != 0


def test_observe_type_needs_click():
    result = runner.invoke(app, ["observe", "https://example.com", "--type", "hi"])
    assert result.exit_code != 0
    assert "--click" in result.output


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
