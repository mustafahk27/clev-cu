# Clev progress

Update this file at the end of every phase and whenever a deviation or open question comes up.

## Phase status

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Skeleton | ✅ Done (2026-09-24) | 13 tests passing, ruff clean |
| 2 | Browser observer + executor | ✅ Done (2026-09-24) | 47 tests + 1 live, ruff clean; 4/5 fixtures |
| 3 | State pipeline | ✅ Done (2026-09-24) | 68 tests + 1 live; recall@200 100%, @1 81% on 31 labels |
| 4 | End-to-end loop (Mock + LLM deciders) | ⏳ Next | Waiting for go-ahead |
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
- Run: `uv run clev observe https://en.wikipedia.org/wiki/Karachi --click e18 --type Muscat --press enter --headed --hold 3`,
  `uv run pytest -q` (offline), `uv run pytest -m live` (hits Wikipedia).
- Perf: `observe()` on a 4,678-element page (Wikipedia/Karachi) takes ~59 ms. The first version took ~239 ms because
  Playwright transfers 5k objects slowly; the script now returns one compact JSON string (rows + context table).

### Phase 3: State pipeline (branch `phase-3/state-pipeline`, stacked on `phase-2/browser-observer`)
- Built: `clev/state/filter.py`, `goal.py` (subgoal parsing + quoted-literal extraction for §10),
  `rank.py` (heuristic scores), `serialize.py` (`build_state()`), `match.py` (`find_same`, moved from the CLI),
  `clev state <fixture> "<goal>"` CLI, 31 hand-labeled steps in `tests/state_labels.py`.
- Observer additions: `Element.editable`, `Observation.viewport`, `article "<heading>"` context (tells apart the
  identical "Add to basket" buttons), id-based fallback names (`dateOfBirthInput` -> "date of birth").
- Results on 31 labeled steps: recall@1 81%, @5 100%, @200 100% (criterion ≥95%). Largest serialized state:
  Wikipedia at ~5.2K tokens (budget 24K). `build_state` takes ~10 ms on the 4.7K-element Wikipedia page.
- Run: `uv run clev state tests/fixtures/wikipedia.json.gz "Open the History section"`, `uv run pytest -q`.

## Deviations from the plan
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
- **Phase 3:**
  - Verb is `type` when `Element.editable` (or role textbox/searchbox), not by role alone. Wikipedia's search box is an
    editable `combobox` once focused, so role-only would offer `click` for it.
  - Options are listed in **page order**; ranking only decides which 200 make the cut. That reads like the screen and
    avoids leaking rank order into the decider.
  - Over budget: names are clipped to 60 chars **before** dropping options (the plan says drop first). Dropping
    candidates is what hurts recall, the risk §14 calls out, and clipping costs almost nothing.
  - Global options use word labels (`SCROLL_DOWN`, `GO_BACK`, `WAIT`, `SUBGOAL_DONE`, `NONE_OF_THESE`, `STUCK`);
    elements use numbers. `SUBGOAL_DONE`/`NONE_OF_THESE`/`STUCK` carry no action; the loop interprets them.
  - Token counts are estimated at 3.5 chars/token (no Jev tokenizer yet). Re-check against real Jev usage in Phase 5.
  - Interactive allowlist also includes menuitemcheckbox/menuitemradio/spinbutton/listbox/treeitem.
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
- [ ] Trace size: full observations are ~1 MB/step on heavy pages (Phase 1 benchmark). Moved to Phase 4, where
  StepRecords get built: trace only the serialized state plus the chosen element, and the full observation only
  when it changes.
- [ ] **For Phase 4:** pages replace elements after actions. Clicking Wikipedia's search box swaps the
  `searchbox` for a new `combobox` node, so the old id goes stale. The loop must re-observe before every action
  (never reuse ids across actions), and history/loop detection should match elements by name, not id or role.
  `clev observe` does this with `find_same()`; move it into `clev/state/` in Phase 3/4.
- [ ] Ranking recall is optimistic: labels were written after seeing the fixtures and weights tuned on them.
  Phase 6 (Mind2Web) is the unbiased check. Known weak spots: repeated names (3 identical "Add to basket"),
  placeholder-only names ("name@example.com" for an email field).
- [ ] `<select>` dropdowns are `combobox` + `click`, but choosing an option needs Playwright's `select_option`.
  Add a `select` action kind in Phase 4 if tasks need it. File inputs (`upload picture`) aren't supported either.
- [ ] Phase 3 branched from `phase-2/browser-observer` (Phase 2 isn't merged into master yet). Merge phase 2 first.
- [ ] Jev API: request/response shapes, real option/context limits, rate limits (Phase 5).
