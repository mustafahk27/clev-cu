import json

from typer.testing import CliRunner

from clev.cli import app

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


def test_state_prints_serialized_options():
    fixture = "tests/fixtures/form.json.gz"
    result = runner.invoke(app, ["state", fixture, "Tick the Reading hobby", "--done", "Open form"])
    assert result.exit_code == 0, result.output
    assert "GOAL: Tick the Reading hobby" in result.output
    assert "DONE SO FAR: 1) Open form" in result.output
    assert "STUCK" in result.output
    best = result.output.split("Best 5 by rank:")[1].splitlines()[1]
    assert "'Reading'" in best
