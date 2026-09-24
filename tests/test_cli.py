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
