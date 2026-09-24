from pathlib import Path

import pytest
from pydantic import ValidationError

from clev.config import Settings, load_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
ENV_KEYS = [
    "DECIDER",
    "MAX_STEPS",
    "DRY_RUN",
    "LLM_PROVIDER",
    "PLANNER_MODEL",
    "ESCALATION_MODEL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CONFIDENCE_THRESHOLD",
]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    # Don't let a developer's real .env or shell env leak into tests.
    monkeypatch.chdir(tmp_path)
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_plan():
    s = Settings()
    assert s.llm_provider == "openai"
    assert s.planner_model == "gpt-6-luna"
    assert s.escalation_model == "gpt-6-luna"
    assert s.decider == "jev"
    assert s.confidence_threshold == 0.6
    assert s.margin == 0.1
    assert s.max_options == 200
    assert s.token_budget == 24000
    assert s.max_steps == 50
    assert s.confirm_destructive is True
    assert s.dry_run is False


def test_env_and_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("DECIDER=mock\nMAX_STEPS=7\n")
    monkeypatch.setenv("DRY_RUN", "true")
    s = Settings()
    assert s.decider == "mock"
    assert s.max_steps == 7
    assert s.dry_run is True


def test_cli_overrides_skip_none(monkeypatch):
    monkeypatch.setenv("DECIDER", "llm")
    s = load_settings(decider=None, max_steps=3)
    assert s.decider == "llm"
    assert s.max_steps == 3


def test_invalid_values_rejected(monkeypatch):
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "1.5")
    with pytest.raises(ValidationError):
        Settings()


def test_redacted_hides_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    data = Settings().redacted()
    assert data["openai_api_key"] == "set"
    assert data["anthropic_api_key"] == "unset"
    assert data["jev_api_key"] == "unset"
    assert "sk-secret" not in str(data)


def test_env_example_is_valid_and_uses_openai():
    s = Settings(_env_file=ENV_EXAMPLE)
    assert s.llm_provider == "openai"
    assert s.planner_model.startswith("gpt-")
    assert s.escalation_model.startswith("gpt-")


def test_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings()
