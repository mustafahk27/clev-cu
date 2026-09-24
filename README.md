# Clev

*Clever enough to know when to think.*

Clev is a fast computer use agent. A small decision model (Jev by TypeSafe AI) picks each UI
action, and a frontier LLM is only called for planning, writing text, and uncertain steps.
See [CLEV_PLAN.md](CLEV_PLAN.md) for the full design and build phases.

## Quickstart

```bash
uv sync
cp .env.example .env   # fill in API keys
uv run clev run "search Wikipedia for Karachi" --mode browser --decider mock
uv run pytest
```

Status: Phase 1 (skeleton). The CLI parses config; the control loop lands in Phase 4.
