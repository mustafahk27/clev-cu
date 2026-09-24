# Clev progress

Update this file at the end of every phase and whenever a deviation or open question comes up.

## Phase status

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Skeleton | ✅ Done (2026-09-24) | 13 tests passing, ruff clean |
| 2 | Browser observer + executor | ⏳ Next | Waiting for go-ahead |
| 3 | State pipeline | — | |
| 4 | End-to-end loop (Mock + LLM deciders) | — | |
| 5 | Jev adapter | — | Needs Jev API access + docs |
| 6 | Offline eval (Mind2Web) | — | |
| 7 | Online eval (WebArena) | — | |
| 8 | macOS desktop mode | — | |
| 9 | Polish and demo | — | |

## Phase log

### Phase 1: Skeleton
- Built: `pyproject.toml` (uv, ruff, pytest-asyncio), `.env.example`, `clev/config.py`,
  `clev/core/types.py`, `clev/core/interfaces.py`, `clev/trace/tracer.py`, `clev/cli.py`
  (`run` prints config, `replay` basic, `eval` stub).
- Run: `uv run clev run "task" --mode browser --decider mock`, `uv run pytest -q`.

## Deviations from the plan
- Added types `Option`, `SerializedState`, `StepRecord` and a `Tracer` protocol (the plan referenced
  but didn't define them).
- `.env.example`: comments sit on their own lines (inline comments can leak into values). Added `TRACE_DIR`.
- `MAX_OPTIONS` validated ≤ 248 so the 7 global options fit Jev's 255 limit.
- Repo root is `clev-cu/`, with the `clev/` package inside.
- LLM provider is configurable (`LLM_PROVIDER`), default **OpenAI**, with `gpt-6-luna` for both planner and escalation, chosen
  for cost (from OpenAI's pricing docs, 2026-09-24). `gpt-6-sol` is the planner upgrade if needed. Anthropic is still supported. Phase 4 adds an `LLMClient`
  protocol with `clev/llm/openai.py` + `clev/llm/anthropic.py`, which are the only files importing those SDKs.

## Open questions
- [ ] Local Python is 3.14. Confirm Playwright supports it at the start of Phase 2; otherwise pin 3.12.
- [x] Git: commits on `master`, remote `mustafahk27/clev-cu`, author `mustafahk27`, one commit per section.
- [ ] Is `gpt-6-luna` good enough as the planner? Measure in Phase 4; fall back to `gpt-6-sol` for planning only.
- [ ] Cheaper still: try `gpt-5-nano` ($0.05/1M in) as escalation model in the Phase 6 sweep.
- [ ] "10x cheaper" goal at risk: Jev input ($42/B = $0.042/1M) is only ~2.4x cheaper than
  `gpt-6-luna` ($0.10/1M), so a luna-only baseline costs about the same as Clev (~$0.012 vs ~$0.009 per task, est.).
  Proposal: compare against several baselines (luna, sol, astra) in Phase 6 and frame the headline as
  "faster, and cheaper at equal quality". Confirm once real Jev pricing is known (Phase 5).
- [ ] Jev API: request/response shapes, real option/context limits, rate limits (Phase 5).
