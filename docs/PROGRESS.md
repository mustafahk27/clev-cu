# Clev progress

Update this file at the end of every phase and whenever a deviation or open question comes up.

## Phase status

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Skeleton | ✅ Done (2026-09-24) | 13 tests passing, ruff clean |
| 2 | Browser observer + executor | ✅ Done (2026-09-24) | 47 tests + 1 live, ruff clean; 4/5 fixtures |
| 3 | State pipeline | ✅ Done (2026-09-24) | 68 tests + 1 live; recall@200 100%, @1 81% on 31 labels |
| 4 | End-to-end loop (Mock + LLM deciders) | ✅ Done (2026-09-25) | 151 tests + 1 live; done-when task succeeds live |
| 5 | Jev adapter | ✅ Done (2026-09-29) | 168 tests + 1 live; done-when task: 4/4 steps by Jev, 0% escalated |
| 6 | Offline eval (Mind2Web) | ✅ Done (2026-09-30) | 500 steps; report in `docs/results/mind2web-500/`; $4.25 spent |
| 7 | Online eval (WebArena) | ⏳ Next | Needs Docker setup (see open questions) |
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

### Phase 3: State pipeline (branch `phase-3/state-pipeline`)
- Built: `clev/state/filter.py`, `goal.py` (subgoal parsing + quoted-literal extraction for §10),
  `rank.py` (heuristic scores), `serialize.py` (`build_state()`), `match.py` (`find_same`, moved from the CLI),
  `clev state <fixture> "<goal>"` CLI, 31 hand-labeled steps in `tests/state_labels.py`.
- Observer additions: `Element.editable`, `Observation.viewport`, `article "<heading>"` context (tells apart the
  identical "Add to basket" buttons), id-based fallback names (`dateOfBirthInput` -> "date of birth").
- Results on 31 labeled steps: recall@1 81%, @5 100%, @200 100% (criterion ≥95%). Largest serialized state:
  Wikipedia at ~5.2K tokens (budget 24K). `build_state` takes ~10 ms on the 4.7K-element Wikipedia page.
- Run: `uv run clev state tests/fixtures/wikipedia.json.gz "Open the History section"`, `uv run pytest -q`.
- Follow-up fix (branch `phase-3/fix-ranking-recall`, 2026-09-25): a check on **unseen** pages found one miss (Hacker
  News "next page" -> link "More", no shared words, cut at rank 221/230). Fixed with wording normalization
  (log in/login, next/more/», newest/new, basket/cart, email placeholders) and 20% reserve slots spread across the
  page. Recall in the serialized options, and target ranked #1:

  | Label set | Before | After |
  |---|---|---|
  | Tuned (31 labels) | 100%, #1 81% | 100%, #1 84% |
  | Held-out 2 (18 labels, `HELDOUT` in `tests/state_labels.py`) | 94%, #1 67% | 100%, #1 78% |
  | Fresh set 3 (15 labels, 5 new sites, run once after the fix, not saved) | – | 100%, #1 80%, top-3 100% |

### Phase 4: End-to-end loop (branch `phase-4/agent-loop`)
- Built: `clev/llm/` (`OpenAIClient`: Responses API + structured outputs, token usage, cost from `pricing.py`),
  `clev/planner/` (`LLMPlanner`: plan with start URL, replan, write_text; prompts mark page text untrusted),
  `clev/decide/llm_decider.py` (label-constrained choice), `clev/decide/mock.py`, `clev/safety/` (destructive-click
  confirmation, credential-field refusal, domain allowlist), `clev/core/loop.py` (`Agent`), `clev run` wired up.
- Loop: plan -> open start URL -> each step observe -> `build_state` -> decide -> gate -> execute -> trace. Replans on
  NONE_OF_THESE/STUCK, 3 failed actions in a row, or the same action 3x; gives up after `MAX_REPLANS`. Typing a
  subgoal's quoted value completes it without another decider call. Ctrl+C still writes an `end` record.
- Live results (`--decider llm`, planner and decider `gpt-6-luna`, headless):

  | Task | Result | Steps | Time | Cost |
  |---|---|---|---|---|
  | search Wikipedia for Karachi and open the article (**done-when**) | ✅ ends on "Karachi - Wikipedia" | 4 | 13.0 s | $0.0013 |
  | open the Muscat article on Wikipedia and go to its History section | ✅ | 2 | 8.0 s | $0.0009 |

  LLM decisions take 1.6–2.7 s per step (~85% of step time): the part Jev should replace. Traces are ~34 KB/step
  (was ~1 MB on heavy pages).
- Found live: Wikipedia's portal search redirects straight to the article, so observing mid-navigation crashed.
  The observer now retries after the page loads, and browser errors surface as `ObservationError`.
- Run: `uv run clev run "search Wikipedia for Karachi and open the article" --decider llm`.

### Phase 5: Jev adapter (branch `phase-5/jev-adapter`)
- Built: `clev/decide/questions.py` (next_action + subgoal_complete / error_visible / progress, one call),
  `clev/decide/jev.py` (`typesafe-sdk` 0.7.2, `jev-1.13.0` pinned, 2 SDK retries, cost from input tokens),
  `clev/decide/escalate.py` (`EscalatingDecider`: plan §9 rules, every escalation has a reason),
  `clev/trace/replay.py` (`clev replay` shows who decided, Jev's confidence, escalations, latency, cost).
  `DECIDER=jev` (Jev + LLM fallback) is the default.
- Smoke test before building: numeric option keys ("1".."200") work; ~440 input tokens for a 5-option call.
- Live results (headless, planner `gpt-6-luna`):

  | Task | Result | Steps (Jev / LLM) | Jev median | Time | Cost |
  |---|---|---|---|---|---|
  | search Wikipedia for Karachi and open the article (**done-when**) | ✅ | 4 / 0 | 522 ms | 9.2 s | $0.0007 |
  | same task, LLM decider (Phase 4, for comparison) | ✅ | 0 / 4 | (LLM 1.6–2.7 s) | 13.0 s | $0.0013 |
  | open the Muscat article and go to its History section | ✅ | 3 / 0 | 827 ms | 8.4 s | $0.0009 |
  | open microsoft/playwright's Issues tab on GitHub | ✅ | 3 / 0 | 447 ms | 15.5 s | $0.0008 |
  | on Hacker News, open the Ask HN page | ✅ | 1 / 0 | 529 ms | 6.2 s | $0.0002 |
  | Karachi task with `CONFIDENCE_THRESHOLD=0.99` (forces escalation) | ✅ | 2 / 2 | 520 ms (LLM 2.4 s) | 11.0 s | $0.0010 |

  Jev decisions are ~4x faster than the LLM's. Most of the remaining cost is the single planner call.
- Run: `uv run clev run "search Wikipedia for Karachi and open the article"`, then `uv run clev replay traces/<run>.jsonl`.

### Phase 6: Offline eval, Mind2Web (branch `phase-6/mind2web-eval`)
- Built: `evals/mind2web/loader.py` (official test splits from `osunlp/Multimodal-Mind2Web`; only the needed parquet
  columns are fetched, ~25 MB instead of ~1 GB of screenshots), `render.py` (each step's saved HTML loaded into
  Chromium and read by **our real observer**), `run.py` (concurrent deciders, answers cached in `evals/cache/`),
  `planned.py` (live-style variant), `evals/report.py` (metrics, escalation simulation, calibration, plots),
  `clev eval mind2web`. Full report: [docs/results/mind2web-500/report.md](results/mind2web-500/report.md).
- 500 steps, 57 websites, 134 tasks, evenly from the task / website / domain test splits. Every decider sees the same
  Clev pipeline output, so only the decider differs.

  | Decider (whole-task goal, Mind2Web's setup) | Element acc | Median ms / decision | $ / 1k steps |
  |---|---|---|---|
  | Jev alone | 26.0% | **395** | **$0.21** |
  | Clev (Jev + luna @ 0.6) | 33.4% (74% escalated) | 2,857 | $0.49 |
  | Clev (Jev + luna @ 0.3) | 31.4% (40% escalated) | 455 | $0.36 |
  | gpt-6-luna alone | 34.6% | 2,761 | $0.37 |
  | gpt-6-sol alone | 38.8% | 3,426 | $7.01 |

- **Findings:**
  1. **Speed and cost hold up; accuracy doesn't, in this setup.** Jev decides ~7x faster than luna and ~9x faster
     than sol, and costs ~1.8x less than luna and ~33x less than sol, but is 8.6 points behind luna and 12.8 behind sol.
  2. **The pipeline ceiling is the biggest limit:** the target is among the 200 options in only 66.8% of steps
     (84.6% exist in Mind2Web's saved HTML, 76.0% are seen by the observer). Unbiased ranking recall: 88% of observed
     targets survive the cut (vs 100% on our own labels). More options help Jev: 21% / 25% / 26% at 50 / 100 / 200.
  3. **Calibration is ordinal but overconfident** (ECE 0.198): accuracy rises steadily with confidence (0% at 0.1–0.2,
     75% at 0.9–1.0), but e.g. confidence 0.54 means 35% accuracy. Good for ranking which steps to escalate; the
     threshold isn't a probability.
  4. **Escalation has no sweet spot here:** accuracy climbs slowly with escalation (31.2% at 35% escalated -> 34.6% at
     91%). At the default 0.6, 74% of steps escalate, which removes most of the speed gain.
  5. **Given the same explicit subgoal, Jev matches the LLM** (live-style variant: Jev 20.2% vs luna 21.0% with
     planner-written subgoals). So Jev's element choice isn't the weakness; working out *what to do next* is. But
     per-step planner subgoals lowered **everyone's** accuracy (35% -> 21%): the planner sees only 40 elements and often
     guesses the wrong next step, and 12% of its subgoals copied Mind2Web's `[tag] name -> OP` history format.
- Mind2Web's standard setup (whole task + past actions per step) makes the decider plan, which live Clev leaves to the
  planner. It measures Jev as a *planner-and-picker*, the hardest case for it. WebArena (Phase 7) tests the real loop.
- Run: `uv sync --extra eval`, then `uv run clev eval mind2web --n 500` (cached answers are reused; a re-run with no new
  deciders makes no model calls).

## Deviations from the plan
- Added types `Option`, `SerializedState`, `StepRecord` and a `Tracer` protocol (the plan referenced
  but didn't define them).
- `.env.example`: comments sit on their own lines (inline comments can leak into values). Added `TRACE_DIR`.
- `MAX_OPTIONS` validated ≤ 247 so the 8 global options (7 in the plan + `PRESS_ENTER`) fit Jev's 255 limit.
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
- **Phase 4:**
  - `Planner.plan()` returns a `Plan` (`start_url` + subgoals) instead of a bare list: the browser starts blank,
    and a new `goto` action (planner-only, never a decider option, checked by the allowlist) opens the site.
  - 8th global option `PRESS_ENTER`: submitting a search box is common and no element represents it.
  - `Decision.action` is optional (None for SUBGOAL_DONE / NONE_OF_THESE / STUCK). `SerializedState.elements`
    maps option labels to elements (not traced). `StepRecord` gained `event` (plan/step/replan/end), `subgoals`,
    `note`, `cost_usd`, `latency_ms`; `observation` is optional and trimmed to the option elements unless
    `TRACE_FULL_OBSERVATIONS=true`.
  - Declining a destructive action, a credential field or an off-allowlist page **ends** the run (plan says
    "pause and ask" / "hand control back"): safest default until there's a hand-back UI.
  - `--dry-run` advances one subgoal per decision, since nothing changes on screen.
  - **Anthropic adapter not built** (no key to test it live). `LLM_PROVIDER=anthropic` errors clearly. The
    `LLMClient` protocol is ready for it.
  - `clev run` now runs the agent; `--show-config` prints the config (the old Phase 1 behaviour).
- **Phase 5:**
  - `progress` is a yes/no ("did the last action move closer to the goal?") instead of a score: TypeSafe's docs
    warn scores are weakly calibrated, and comparing two screens adds unrelated state (plan §8, consequence 3).
    It's only asked once there's a previous action.
  - The confidence threshold uses Jev's `confidence` field (computed from the whole distribution; ≈ top
    probability at our option counts), plus the plan's margin rule on the top two probabilities.
  - `subgoal_complete` > `DONE_THRESHOLD` becomes SUBGOAL_DONE and `error_visible` > `ERROR_THRESHOLD` becomes STUCK
    (-> replan) **before** the escalation rules run, so completion is decided by Jev at ~0.5 s, not the LLM at ~2 s.
  - Repeats escalate on the 3rd identical action (matched by role + name, since ids change); if the LLM repeats
    it anyway, the loop's own 3-repeat rule replans.
  - Escalated steps are `decided_by="llm"`; Jev's own answer is kept in `primary_choice/confidence/probs`
    for Phase 6 calibration.
  - Touched beyond `decide/jev.py` + `decide/escalate.py`: `Decision` gained optional fields, `SerializedState.header`,
    the loop copies escalation info into `StepRecord`, and the CLI/replay wiring.
- **Phase 6:**
  - Data from `osunlp/Multimodal-Mind2Web` (official test splits as parquet), first shard of each split, 500 steps
    sampled evenly. The original `test.zip` is password-protected to avoid crawling; the parquet copy isn't.
  - Mind2Web's cleaned HTML drops `href` from links and renames `aria-*` to `aria_*`; the eval renderer restores both
    before our observer reads it (eval-only; the live observer is unchanged).
  - Two element scores: **strict** (exact Mind2Web element) and **equivalent** (headline: the target's `<label>`
    input, or a link/button wrapping the target text, i.e. the same click). Action accuracy = equivalent element +
    right verb; typed values aren't scored (they come from the planner, not the decider).
  - Jev + escalation is **simulated** from recorded Jev and luna answers with the per-step rules (confidence, margin,
    NONE_OF_THESE/STUCK, subgoal_complete/error_visible, Jev errors). History rules (repeats, no progress) need a
    live loop, so they're not in the offline number.
  - Baselines: luna and sol. Astra was skipped for cost (~$32 for 500 steps).
  - "The planner model as decider" (plan) = luna here, since planner and escalation model are both `gpt-6-luna`; sol
    was added as the stronger baseline.
  - Extra: the live-style variant (planner-written subgoal per step), to separate planning from picking.
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
- [x] `gpt-6-luna` as planner: fine on both live tasks (sensible subgoals, quoted values, direct start URLs).
  Re-check on harder tasks in Phase 7.
- [ ] Cheaper still: try `gpt-5-nano` ($0.05/1M in) as escalation model in the Phase 6 sweep.
- [ ] "10x cheaper" goal at risk: Jev input ($42/B = $0.042/1M) is only ~2.4x cheaper than
  `gpt-6-luna` ($0.10/1M), so a luna-only baseline costs about the same as Clev (~$0.012 vs ~$0.009 per task, est.).
  Proposal: compare against several baselines (luna, sol, astra) in Phase 6 and frame the headline as
  "faster, and cheaper at equal quality". Confirm once real Jev pricing is known (Phase 5).
- [ ] **Gmail-like fixture missing.** Gmail needs login (and a real inbox must never go in git); the public
  webmail demos tried (Mailpit, Roundcube) didn't load. Options: (a) a synthetic inbox page in `tests/fixtures/pages/`,
  (b) a public webmail demo you know, (c) skip it; WebArena has no mail app anyway.
- [x] Trace size: steps keep only the option elements (~34 KB/step live, was ~1 MB). Full pages with
  `TRACE_FULL_OBSERVATIONS=true`.
- [x] Element replacement: the loop re-observes before every step and never reuses ids; loop detection
  compares role + name, not ids.
- [ ] Ranking recall on our own labels is optimistic: the tuned set was used to set weights, and held-out set 2
  shaped the recall fix. Set 3 (15 labels) is the most honest number so far. Phase 6 (Mind2Web) is the real check. Known weak spots: repeated names (3 identical "Add to basket"),
  placeholder-only names ("name@example.com" for an email field).
- [ ] `<select>` dropdowns are `combobox` + `click`, but choosing an option needs Playwright's `select_option`.
  Not needed by the Phase 4 tasks; add a `select` action when a WebArena task needs it. File uploads aren't
  supported either.
- [x] Completion after a click now costs one Jev call (~0.5 s) instead of an LLM step (~2 s).
- [ ] Could go further: when Jev says a subgoal is complete, also ask `next_action` for the **next** subgoal in the
  same call (TypeSafe's fan-out pattern), saving a round trip per subgoal.
- [ ] Planner sometimes emits redundant subgoals ("Click the Issues tab" then "Open the Issues page"). Jev clears
  them in ~0.5 s, but a prompt tweak could remove them.
- [x] Jev latency on Mind2Web: median 376 / 379 / 395 ms at 50 / 100 / 200 options (p95 495–566 ms), so option
  count barely affects it. Within the plan's 70–500 ms at the median.
- [ ] **Threshold decision needed.** Mind2Web: 0.6 escalates 74% of steps (slow); 0.3 escalates 40% for -2 points.
  Live runs with planner subgoals: 0.6 escalated 0%. The right value depends on the task mix, so keep 0.6 until
  WebArena (Phase 7) measures the real loop, then pick from that sweep.
- [ ] **Biggest accuracy lever is recall, not the decider:** the target reaches the options in only 67% of Mind2Web
  steps. Candidates: detect JS-only clickables (`cursor:pointer`/`onclick` divs and spans) in the observer, and
  better ranking (plan's v2: embeddings). Tune on train-split data, never on the test steps above.
- [ ] Planner subgoal quality: it sees only 40 elements, and it sometimes copies action-log formats. Show it more of
  the page (or the ranked top candidates) and phrase history as sentences.
- [ ] Jev is overconfident (ECE 0.198; 0.464 with planner subgoals). If needed, recalibrate its confidence on
  train-split data (e.g. isotonic) before thresholding.
- [ ] Headline framing: per-decision speed (~7x vs luna) and cost (~33x vs sol) are real; "within a few points" holds
  only with heavy escalation in this setup. Confirm on WebArena before writing the headline chart.
- [ ] Anthropic `LLMClient` adapter (deferred from Phase 4; needs a key to test live).
- [ ] Safety word lists err on the side of asking ("Payment methods" link counts as destructive). Tune if it
  gets annoying; never loosen the credential rule.
- [x] Jev API: read TypeSafe's docs (2026-09-25). Shapes, limits, pricing and 6 design consequences are in
  CLEV_PLAN.md §8 under "Confirmed from TypeSafe's docs". Pricing matches the plan ($42/B input, output free).
