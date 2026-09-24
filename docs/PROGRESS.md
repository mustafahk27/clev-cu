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

## Open questions
- [ ] Local Python is 3.14. Confirm Playwright supports it at the start of Phase 2; otherwise pin 3.12.
- [ ] Not a git repo yet. `git init` + first commit?
- [ ] Jev API: request/response shapes, real option/context limits, rate limits (Phase 5).
