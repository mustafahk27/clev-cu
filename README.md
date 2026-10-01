# Clev

*Clever enough to know when to think.*

Clev is a fast computer use agent. A small decision model (Jev by TypeSafe AI) picks each UI
action, and a frontier LLM is only called for planning, writing text, and uncertain steps.
See [CLEV_PLAN.md](CLEV_PLAN.md) for the full design and build phases.

## Quickstart

```bash
uv sync
uv run playwright install chromium
cp .env.example .env   # fill in API keys
uv run clev run "search Wikipedia for Karachi and open the article"   # Jev + LLM fallback (default)
uv run clev replay traces/<run>.jsonl                                   # who decided each step
uv run clev observe https://en.wikipedia.org/wiki/Karachi            # list elements
uv run clev observe https://en.wikipedia.org/wiki/Karachi --click e33 # click one by id
uv run clev observe https://en.wikipedia.org/wiki/Karachi --click e18 --type Muscat --press enter --headed --hold 3
uv run clev state tests/fixtures/wikipedia.json.gz "Open the History section"  # what the decider sees
uv sync --extra eval && uv run clev eval mind2web --n 500   # offline eval report
uv run pytest            # offline tests
uv run pytest -m live    # tests that hit real sites
```

Status: Phase 6 (offline eval). Mind2Web results: [docs/results/mind2web-500-v2/report.md](docs/results/mind2web-500-v2/report.md) (first run: [mind2web-500](docs/results/mind2web-500/report.md)). The control loop lands in Phase 4.
Progress and open questions: [docs/PROGRESS.md](docs/PROGRESS.md).
