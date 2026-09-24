# Clev progress

Update this file at the end of every phase and whenever a deviation or open question comes up.

## Phase status

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Skeleton | ✅ Done (2026-09-24) | 13 tests passing, ruff clean |
| 2 | Browser observer + executor | ✅ Done (2026-09-24) | 47 tests + 1 live, ruff clean; 4/5 fixtures |
| 3 | State pipeline | ⏳ Next | Waiting for go-ahead |
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

### Phase 2: Browser observer + executor (branch `phase-2/browser-observer`)
- Built: `clev/observe/browser.py` (`BrowserSession`, `BrowserObserver`), `clev/observe/dom_snapshot.js`,
  `clev/observe/io.py` (fixture save/load), `clev/execute/browser.py` (`BrowserExecutor`),
  `clev/core/errors.py`, `clev observe` CLI command, `scripts/capture_fixtures.py`, fixtures in `tests/fixtures/`.
- Run: `uv run clev observe https://en.wikipedia.org/wiki/Karachi --click e33`,
  `uv run pytest -q` (offline), `uv run pytest -m live` (hits Wikipedia).
- Perf: `observe()` on a 4,678-element page (Wikipedia/Karachi) takes ~59 ms. The first version took ~239 ms because
  Playwright transfers 5k objects slowly; the script now returns one compact JSON string (rows + context table).


- Added types `Option`, `SerializedState`, `StepRecord` and a `Tracer` protocol (the plan referenced
  but didn't define them).
- `.env.example`: comments sit on their own lines (inline comments can leak into values). Added `TRACE_DIR`.
- `MAX_OPTIONS` validated ≤ 248 so the 7 global options fit Jev's 255 limit.
- Repo root is `clev-cu/`, with the `clev/` package inside.
- Observer uses one in-page DOM walk, not Playwright's accessibility snapshot + DOM merge. Playwright no longer
  exposes a handle-bearing AX snapshot, and per-node CDP lookups are too slow for 5k nodes. Roles and names are a
  simplified accessible-name computation (aria-labelledby, aria-label, `<label>`, placeholder, alt, text).
  Element handles come from live references kept in `window.__clev`, which leaves the page's DOM untouched.
  Stale ids (older observation or after navigation) raise `StaleElementError`.
- Not covered yet: iframes (same-origin iframe content is skipped) and closed shadow roots.
- Observer emits interactive elements plus `heading`/`alert`/`status` for context; Phase 3 filters.
  `visible` means rendered (non-zero size, not hidden), so off-screen elements count as visible.
- Secret values (password inputs, `autocomplete` cc-*/one-time-code/…-password) are recorded as `[redacted]`.
- `type` always replaces the field (Playwright `fill`); "append" mode from plan §10 isn't supported yet
  because `Action` has no append flag. Add one in Phase 4 if the planner needs it.
- Added `HEADLESS` setting (default false, so you can watch the browser; tests run headless).
- Fixtures: "Amazon-like" uses `books.toscrape.com` (Amazon's ToS forbids bots; nopCommerce/OpenCart demos are
  behind Cloudflare bot checks, which we don't bypass). "Form-heavy" uses demoqa's practice form.
- LLM provider is configurable (`LLM_PROVIDER`), default **OpenAI**, with `gpt-6-luna` for both planner and escalation, chosen
  for cost (from OpenAI's pricing docs, 2026-09-24). `gpt-6-sol` is the planner upgrade if needed. Anthropic is still supported. Phase 4 adds an `LLMClient`
  protocol with `clev/llm/openai.py` + `clev/llm/anthropic.py`, which are the only files importing those SDKs.

## Open questions
- [x] Python 3.14 works with Playwright 1.63 (Chromium 153). No pin needed.
- [x] Git: commits on `master`, remote `mustafahk27/clev-cu`, author `mustafahk27`, one commit per section.
- [ ] Is `gpt-6-luna` good enough as the planner? Measure in Phase 4; fall back to `gpt-6-sol` for planning only.
- [ ] Cheaper still: try `gpt-5-nano` ($0.05/1M in) as escalation model in the Phase 6 sweep.
- [ ] "10x cheaper" goal at risk: Jev input ($42/B = $0.042/1M) is only ~2.4x cheaper than
  `gpt-6-luna` ($0.10/1M), so a luna-only baseline costs about the same as Clev (~$0.012 vs ~$0.009 per task, est.).
  Proposal: compare against several baselines (luna, sol, astra) in Phase 6 and frame the headline as
  "faster, and cheaper at equal quality". Confirm once real Jev pricing is known (Phase 5).
- [ ] **Gmail-like fixture missing.** Gmail needs login (and a real inbox must never go in git); the public
  webmail demos tried (Mailpit, Roundcube) didn't load. Options: (a) a synthetic inbox page in `tests/fixtures/pages/`,
  (b) a public webmail demo you know, (c) skip it; WebArena has no mail app anyway.
- [ ] Trace size: full observations are ~1 MB/step on heavy pages (Phase 1 benchmark). Plan: trace only the
  filtered candidates in Phase 3, and store the full observation only when it changes in Phase 4.
- [ ] Jev API: request/response shapes, real option/context limits, rate limits (Phase 5).
