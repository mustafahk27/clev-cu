# Clev: Build Plan

Clev is a fast computer use agent. A small decision model (Jev by TypeSafe AI) picks every UI action in milliseconds, and a frontier LLM is only called for planning, writing text, and steps where Jev is unsure.

Tagline: *clever enough to know when to think.*

---

## 0. Instructions for Claude Code

Read this whole file before writing any code. Then follow these rules:

1. Work **one phase at a time** (Section 12). At the end of each phase, stop, summarize what was built, show how to run it, list anything unresolved, and **wait for my confirmation** before starting the next phase.
2. Prefer small, targeted changes. When fixing a bug, change only what's needed. Do not rewrite working modules.
3. Every external dependency (Jev, LLM APIs, OS automation) sits behind an interface defined in `clev/core/interfaces.py`. Nothing outside the adapter modules imports a vendor SDK directly.
4. Jev access is waitlist-only and its SDK details may not match what's assumed here. Build the `MockDecider` first so everything runs without Jev. When wiring the real Jev adapter, read TypeSafe's official docs and adjust the adapter only, not the core loop.
5. Never hardcode API keys. Load from environment variables via `.env` (and ship `.env.example`).
6. Write tests alongside code. Each phase must pass `pytest` before I'm asked to confirm.
7. If something in this plan is ambiguous or wrong once you see real APIs, flag it and propose a fix instead of silently improvising.

---

## 1. Goal

Build an agent that completes computer tasks from a natural-language instruction and is:

- **10x+ faster per step** than an LLM-only computer use agent
- **10x+ cheaper per task**
- **within a few points of task success rate** on standard benchmarks

The headline deliverable is one chart: Clev vs LLM-only agents on success rate, seconds per task, and cost per task.

### Non-goals (for v1)

- No screenshot / vision pipeline. Clev reads accessibility trees and DOM, not pixels.
- No Windows or Linux desktop support in v1 (design for it, don't build it).
- No training or fine-tuning of models.
- No mobile.

---

## 2. Core idea

Most computer use steps are the same question: *"Given this screen and this goal, which element do I act on next?"* That is a multiple-choice decision, not text generation. Jev answers typed questions (choice, score, yes/no probability) over up to 255 options in one parallel pass, in roughly 70 to 500ms, with a 32K context window. It returns calibrated probabilities, which gives us a natural confidence signal for when to escalate to an LLM.

What Jev cannot do, and how Clev handles it:

| Jev limitation | Clev's answer |
|---|---|
| No image input (as far as published) | Observe via accessibility tree (desktop) and DOM/AX tree (browser) |
| Cannot generate strings | Planner LLM supplies any text to type |
| One decision at a time, no long planning | Planner LLM breaks the task into subgoals |
| Max 255 options, 32K context | Candidate filtering and compact state serialization |

---

## 3. Architecture

```
            user task
                |
                v
        +---------------+
        |   Planner     |  (LLM, called rarely)
        | subgoals +    |
        | text slots    |
        +-------+-------+
                |
                v
   +--------------------------+
   |      Control Loop        |<--------------------+
   +--------------------------+                     |
     |        |          |                          |
     v        v          v                          |
 Observer  Serializer  Decider (Jev)                |
 (AX/DOM)  (compact    choice + checks              |
            state,         |                        |
            <=255 opts)    |                        |
                           v                        |
                  confidence >= threshold?          |
                   yes |            | no            |
                       |            v               |
                       |      Escalator (LLM)       |
                       v            |               |
                   Safety Gate <----+               |
                       |                            |
                       v                            |
                   Executor (click/type/key/scroll) |
                       |                            |
                       +------> Tracer (log) -------+
```

### Components

- **Planner** (`clev/planner/`): Takes the task, returns an ordered list of subgoals. Also called on demand to produce text for a typing action (e.g. an email body, a search query). Uses an LLM provider (OpenAI by default, Anthropic supported) via the `LLMClient` adapter.
- **Observer** (`clev/observe/`): Captures the current UI as a tree of elements with role, name, value, state (enabled, focused, visible), bounds, and parent context.
- **Serializer** (`clev/state/`): Filters and ranks elements, then renders the top candidates as compact numbered lines that fit the token budget.
- **Decider** (`clev/decide/`): Sends the serialized state plus typed questions to Jev. Returns chosen action and probabilities.
- **Escalator** (`clev/decide/escalate.py`): When Jev's confidence is low or it picks `NONE_OF_THESE` / `STUCK`, sends the same state to an LLM for that single step.
- **Safety Gate** (`clev/safety/`): Checks the chosen action against rules before execution.
- **Executor** (`clev/execute/`): Performs the action via Playwright (browser) or macOS Accessibility APIs (desktop).
- **Tracer** (`clev/trace/`): Logs every step (observation, options, probabilities, decision, who decided, latency, cost) to JSONL for replay and evaluation.

---

## 4. Tech stack

- **Language:** Python 3.11+
- **Package manager:** `uv`
- **Browser automation:** Playwright (Chromium), using its accessibility snapshot and DOM
- **Desktop automation (macOS):** `pyobjc` with `ApplicationServices` / `AXUIElement` APIs
- **Planner / Escalator LLM:** provider selected by `LLM_PROVIDER` (default `openai`, also `anthropic`). OpenAI default: `gpt-6-luna` for both planning and escalation (cheapest current-gen model: $0.10 in / $0.50 out per 1M tokens). Upgrade the planner to `gpt-6-sol` if plan quality is poor. Anthropic equivalents: `claude-sonnet-5` / `claude-haiku-4-5-20251001`. All configurable.
- **Decision model:** Jev (TypeSafe AI), behind the `Decider` interface
- **Config:** `pydantic-settings`, `.env`
- **CLI:** `typer`
- **Tests:** `pytest`, `pytest-asyncio`
- **Lint/format:** `ruff`
- **Eval plots:** `matplotlib`

Everything async (`asyncio`) so observation and decision calls can overlap.

---

## 5. Repo layout

```
clev-cu/                    # repo root
  pyproject.toml
  .env.example
  README.md
  CLEV_PLAN.md
  CLAUDE.md                 # instructions Claude Code loads every session
  docs/PROGRESS.md          # phase tracker, deviations, open questions
  .claude/commands/         # /next-phase, /phase-check, /flag slash commands
  clev/
    __init__.py
    cli.py                  # `clev run "task"`, `clev replay`, `clev eval`
    config.py
    core/
      interfaces.py         # Protocols: Observer, Decider, Planner, Executor, Tracer
      types.py              # Element, Observation, Action, Option, SerializedState, Decision, StepRecord
      loop.py               # the control loop
    llm/
      openai.py             # LLMClient adapter (default provider)
      anthropic.py          # LLMClient adapter
    planner/
      planner.py            # plan / write_text / replan on top of LLMClient
      prompts.py
    observe/
      browser.py            # Playwright observer
      macos.py              # AX API observer
    state/
      filter.py             # visibility / interactivity filtering
      rank.py               # candidate ranking (heuristic, then optional embeddings)
      serialize.py          # compact text rendering within token budget
    decide/
      questions.py          # typed question definitions
      jev.py                # real Jev adapter
      mock.py               # MockDecider (heuristic + random, for dev)
      llm_decider.py        # LLM-only decider (baseline + escalation)
      escalate.py           # confidence policy
    safety/
      rules.py
      gate.py
    execute/
      browser.py
      macos.py
    trace/
      tracer.py
      replay.py
  evals/
    mind2web/               # offline step-level eval
    webarena/               # online task-level eval
    report.py               # builds the headline chart + tables
  tests/
```

---

## 6. Core types and interfaces

Define these first (Phase 1). Keep them stable. The implemented versions live in `clev/core/types.py` and `clev/core/interfaces.py` (they add `Option`, `SerializedState`, `StepRecord`, and a `Tracer` protocol).

```python
# clev/core/types.py (sketch)

class Element(BaseModel):
    id: str                  # stable within one observation
    role: str                # button, link, textbox, menuitem, checkbox...
    name: str                # accessible name / label
    value: str | None
    context: str             # short path of ancestor names, e.g. "Compose > Toolbar"
    enabled: bool
    focused: bool
    visible: bool
    bounds: tuple[int, int, int, int] | None

class Observation(BaseModel):
    app: str                 # "chromium", "Mail", ...
    title: str               # window / page title
    url: str | None
    elements: list[Element]
    timestamp: float

class Action(BaseModel):
    kind: Literal["click", "type", "key", "scroll", "back", "wait", "done", "fail"]
    element_id: str | None = None
    text: str | None = None       # filled by planner for "type"
    key: str | None = None        # e.g. "cmd+enter"
    direction: Literal["up", "down"] | None = None

class Decision(BaseModel):
    action: Action
    confidence: float             # probability of the chosen option
    probs: dict[str, float]       # option label -> probability
    decided_by: Literal["jev", "llm", "mock"]
    latency_ms: float
    cost_usd: float
```

```python
# clev/core/interfaces.py (sketch)

class Observer(Protocol):
    async def observe(self) -> Observation: ...

class Decider(Protocol):
    async def decide(self, state: SerializedState, subgoal: str,
                     history: list[StepRecord]) -> Decision: ...
    async def check(self, state: SerializedState, question: str) -> float: ...

class Planner(Protocol):
    async def plan(self, task: str, obs: Observation) -> list[str]: ...
    async def write_text(self, task: str, subgoal: str, field: Element) -> str: ...
    async def replan(self, task: str, done: list[str], obs: Observation, reason: str) -> list[str]: ...

class Executor(Protocol):
    async def execute(self, action: Action, obs: Observation) -> None: ...
```

---

## 7. State representation (the hardest part)

A real accessibility tree can have thousands of nodes. Jev takes at most 255 options and 32K tokens. Pipeline:

1. **Filter** (`state/filter.py`): keep elements that are visible, enabled, and interactive (role in an allowlist: button, link, textbox, searchbox, combobox, checkbox, radio, menuitem, tab, option, switch, slider). Keep up to ~30 non-interactive text nodes nearby for context (headings, labels, error messages).
2. **Rank** (`state/rank.py`): score each interactive element against the current subgoal. v1 heuristic: token overlap between subgoal and `name + context`, bonus for focused element, bonus for elements in the topmost dialog/modal, penalty for nav/footer regions. v2 (later phase): small local embedding model.
3. **Select**: keep top `K` (default 200) so there's headroom for global options.
4. **Serialize** (`state/serialize.py`): one line per option, numbered, e.g.

```
APP: Chromium | TITLE: Inbox - Gmail | URL: mail.google.com/...
GOAL: Open the compose window
DONE SO FAR: 1) Opened Gmail
CONTEXT: [h] Inbox (1,204) | [text] "No new messages"
OPTIONS:
 1 click  button "Compose"            @ Sidebar
 2 click  link   "Inbox"              @ Sidebar
 3 type   searchbox "Search mail"     @ Header
 ...
```

5. **Global options** always appended: `scroll down`, `scroll up`, `go back`, `wait`, `SUBGOAL_DONE`, `NONE_OF_THESE`, `STUCK`.
6. **Token budget**: measure serialized length; if over budget (default 24K tokens, leaving room for questions), drop lowest-ranked options first, then truncate long names to 60 chars.

The verb shown per element (click vs type) is derived from role. Textboxes/searchboxes get `type`, everything else gets `click`.

Unit test this module heavily with saved tree fixtures from real sites and apps.

---

## 8. Jev questions

Defined in `decide/questions.py`. One Jev call per step, with several typed questions answered in parallel:

| Question | Type | Purpose |
|---|---|---|
| `next_action`: which option best advances the current goal? | choice over serialized options | The main decision |
| `subgoal_complete`: is the current goal already achieved on this screen? | boolean probability | Advance to next subgoal |
| `error_visible`: is an error, warning, or unexpected dialog on screen? | boolean probability | Trigger replan |
| `progress`: how much closer is this screen to the goal than the last one? | score | Detect loops / no progress |

Adapter notes for `decide/jev.py`:

- Map Jev's primitives (choice, score, null/boolean) onto these questions. Exact request/response shapes must come from TypeSafe's docs.
- Record input tokens for cost tracking (input priced at $42 per billion tokens, output free, per launch coverage; make pricing configurable).
- Retries with exponential backoff; on repeated failure, fall through to the LLM decider for that step.

### Confirmed from TypeSafe's docs (docs.typesafe.ai/api, read 2026-09-25)

- **API:** `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <key>`. Body: `model`, `state`
  (string, object or array; text only), `questions` (map of id to question). All questions in one call (fan-out).
- **SDK:** `typesafe-sdk` (`uv add typesafe-sdk`), `AsyncTypeSafeClient(api_key=..., base_url=..., model=..., retry=..., timeout=...)`,
  `await client.system_one(state=..., questions={...})`. Question types `Choice`, `Noul`, `Score`.
  Response: `.choices[id].choice / .probabilities / .confidence`, `.nouls[id].noul`, `.scores[id].score`, `.usage.input_tokens`.
- **Question types:** `choice` (criteria = map of option key to description, **max 255**), `noul` (yes/no probability,
  no confidence), `score` (2-10 rubric levels; docs warn of weak numeric calibration).
- **Model:** `jev-1.13.0` (alias `jev-latest`). Context: **64K per request; 32K for `state` plus the longest question**.
  Price: $42 per billion input tokens, output free. Rate limit: 250K tokens/s, 1,200 requests/min.
- **Confidence** is computed from the whole distribution, ≈ (N·p_max − 1)/(N − 1), so with ~200 options it's close
  to p_max. Docs suggest >0.9 act automatically, 0.5–0.9 act with care, <0.5 fall back.
- **Known weaknesses (jev-1.13):** takes questions literally; can't count or do arithmetic; "accuracy falls as the
  state grows with content unrelated to the decision"; vulnerable to prompt injection in state.

### Design consequences for Phase 5

1. `next_action` is a `choice` question whose **criteria are the options** (key = option label, value = option line).
   `state` is an object with the page header, goal, done-so-far and context. The 32K limit covers state + the options,
   so the existing 24K `TOKEN_BUDGET` still leaves room for instructions. `SerializedState` needs the header exposed
   separately from the option lines.
2. Use Jev's `confidence` field for the threshold (≈ top probability at our option counts); keep the margin rule.
   Destructive actions need a higher bar (e.g. 0.9) on top of user confirmation.
3. `progress` as a `score` comparing two screens adds unrelated state (a known accuracy drag) and scores are weakly
   calibrated. Proposal: a `noul` "Did the last action move closer to the goal?" with the last action as text.
4. Fewer, better options may beat 200 (distractors hurt). Sweep `MAX_OPTIONS` (50/100/200) in Phase 6.
5. Criteria-key rules aren't documented; examples use lowercase ids. Check that "1".."200" work; else use "o1".."o200".
6. Pin `JEV_MODEL=jev-1.13.0` for reproducible evals, and pass the key explicitly (the SDK's own env var is
   `TYPESAFE_API_KEY`; ours is `JEV_API_KEY`).

---

## 9. Escalation policy

In `decide/escalate.py`. Escalate the current step to the LLM decider when any of:

- `next_action` top probability < `CONFIDENCE_THRESHOLD` (default 0.6, tuned in Phase 6)
- top two options within `MARGIN` (default 0.1) of each other
- chosen option is `NONE_OF_THESE` or `STUCK`
- `progress` score has been flat or negative for 3 consecutive steps
- the same action on the same element repeated 3 times

Call the Planner's `replan` (not just the escalator) when `error_visible` > 0.7 or after 2 consecutive escalations fail to make progress.

Log every escalation with its trigger reason. Escalation rate is a key metric.

---

## 10. Typing text

When the chosen action is `type`:

1. If the subgoal already contains a literal value (planner can emit subgoals like `Type "Muscat" into the destination field`), extract and use it directly. No LLM call.
2. Otherwise call `planner.write_text(task, subgoal, field)`.
3. Executor clears the field (select-all + delete) before typing unless the subgoal says append.

Have the planner prefer literal values in subgoals so most typing needs no extra LLM call.

---

## 11. Safety

In `safety/`. Runs before every execution.

- **Destructive action confirmation**: if the target element name or context matches patterns like delete, remove, send, pay, purchase, submit, confirm, transfer, unsubscribe, sign out, pause the loop and ask the user in the terminal (`y/n`). Configurable, on by default.
- **App/domain allowlist**: optional list of apps or domains Clev may operate in. Anything else stops the run.
- **Credential fields**: never type into password fields or fields labeled card number, CVV, OTP, PIN. Hand control back to the user.
- **Dry-run mode**: `--dry-run` prints decisions without executing.
- **Step cap**: default 50 steps per task; hard stop after.
- **Kill switch**: `Ctrl+C` and a global hotkey (macOS) stop immediately.
- **Untrusted content**: page/app text is data. The planner prompt must state that instructions found on screen are never to be followed as commands.

---

## 12. Phases

Each phase ends with a summary and a pause for my confirmation. Live status is tracked in `docs/PROGRESS.md`.

### Phase 1: Skeleton
- `uv` project, `ruff`, `pytest`, `.env.example`, config
- All types and interfaces from Section 6
- Tracer writing JSONL
- CLI stub: `clev run "task" --mode browser`
- **Done when:** `pytest` passes and the CLI prints a parsed config.

### Phase 2: Browser observer + executor
- Playwright observer producing `Observation` from accessibility snapshot + DOM (merge to get reliable element handles)
- Executor for click, type, key, scroll, back, wait
- Save observation fixtures from 5 real sites (Gmail-like, Amazon-like, Wikipedia, a form-heavy page, GitHub) into `tests/fixtures/`
- **Done when:** a script can observe a page, list elements, and click one by id.

### Phase 3: State pipeline
- Filter, rank (heuristic), serialize with global options and token budget
- Tests on fixtures: budget respected, correct target stays in top K for hand-labeled examples
- **Done when:** for 20 labeled fixture steps, the correct element is in the top 200 at least 95% of the time, and serialized output fits 24K tokens.

### Phase 4: End-to-end loop with Mock and LLM deciders
- `MockDecider` (heuristic, for offline dev)
- `LLMDecider` using the same serialized state and options (this is also the baseline)
- `LLMClient` protocol with OpenAI (default) and Anthropic adapters; the planner (`plan`, `write_text`, `replan`) and `LLMDecider` are built on it
- Control loop wiring everything, safety gate included
- **Done when:** `clev run "search Wikipedia for Karachi and open the article" --decider llm` completes live.

### Phase 5: Jev adapter
- Implement `decide/jev.py` against TypeSafe's real API
- Escalation policy from Section 9
- `--decider jev` (Jev with LLM escalation) becomes the default
- **Done when:** the Phase 4 demo task completes with `--decider jev`, and the trace shows which steps Jev decided vs escalated.

### Phase 6: Offline eval (Mind2Web)
- Loader for Mind2Web step data mapped into Clev's `Observation`
- Step-level metrics: element accuracy, action accuracy, latency, cost
- Compare: Jev alone, Jev + escalation, the escalation model as decider, the planner model as decider
- Calibration: reliability diagram and ECE for Jev's `next_action` confidence
- Sweep `CONFIDENCE_THRESHOLD` to plot accuracy vs escalation rate vs cost
- **Done when:** `clev eval mind2web --n 500` produces a report with tables and plots.

### Phase 7: Online eval (WebArena)
- Docker setup instructions for WebArena environments
- Task runner with success checking per WebArena's evaluators
- Same comparisons as Phase 6, plus seconds per task and cost per task
- **Done when:** results on at least 100 WebArena tasks for Clev and the LLM-only baseline, plus the headline chart.

### Phase 8: macOS desktop mode
- AX API observer (`pyobjc`) and executor (AX actions, CGEvent for keys)
- Permissions check with clear instructions if Accessibility access is missing
- Reuse state, decide, safety, trace unchanged
- **Done when:** `clev run "open Notes and create a note titled Clev test" --mode desktop` works.

### Phase 9: Polish and demo
- README with the headline chart, architecture diagram, quickstart
- `clev replay trace.jsonl` renders a step-by-step view (terminal or simple HTML) showing options, probabilities, and who decided
- Side-by-side demo script: same task, Clev vs LLM-only agent, with timings
- Optional: voice trigger hook so an external voice agent can call `clev run`

---

## 13. Metrics to track everywhere

- Task success rate
- Step accuracy (offline)
- Median and p95 latency per step
- Seconds per task
- Cost per task (Jev + LLM, broken out)
- Escalation rate and escalation reasons
- Calibration (ECE) of Jev confidence
- Steps per task vs human/reference trajectory length

All derived from traces, so every run is re-analyzable later.

---

## 14. Risks and open questions

- **Jev API shape unknown**: mitigated by the adapter pattern and MockDecider. Confirm real limits (options per question, context size, rate limits, latency) in Phase 5 and update this plan.
- **Accessibility trees are messy**: some apps expose poor labels. Track which apps fail and why in traces. Vision fallback is a possible v2.
- **Candidate ranking misses the right element**: the whole system fails silently if the target is filtered out. Phase 3 recall metric exists for this. `NONE_OF_THESE` gives Jev a way to signal it.
- **Calibration may be worse on UI tasks than advertised**: Phase 6 measures it directly. If poor, fall back to margin-based escalation.
- **WebArena setup is heavy**: Mind2Web offline eval comes first so results exist even if WebArena slips.
- **Benchmark fairness**: baselines must use the same observation and option list, so the comparison isolates the decider.

---

## 15. Config defaults (`.env.example`)

```
# openai | anthropic
LLM_PROVIDER=openai
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
JEV_API_KEY=
JEV_BASE_URL=
PLANNER_MODEL=gpt-6-luna          # upgrade: gpt-6-sol; anthropic: claude-sonnet-5
ESCALATION_MODEL=gpt-6-luna       # anthropic: claude-haiku-4-5-20251001
# jev | llm | mock
DECIDER=jev
CONFIDENCE_THRESHOLD=0.6
MARGIN=0.1
JEV_MODEL=jev-1.13.0
JEV_TIMEOUT_S=15
# Jev's subgoal_complete / error_visible probabilities that end a subgoal / trigger a replan
DONE_THRESHOLD=0.7
ERROR_THRESHOLD=0.7
MAX_OPTIONS=200            # capped at 247 so the 8 global options fit in Jev's 255
TOKEN_BUDGET=24000
MAX_STEPS=50
HEADLESS=false
# Comma-separated domains Clev may operate on (empty = any), e.g. wikipedia.org,github.com
ALLOWED_DOMAINS=
MAX_REPLANS=3
LLM_REASONING_EFFORT=low
LLM_TIMEOUT_S=60
TRACE_FULL_OBSERVATIONS=false
CONFIRM_DESTRUCTIVE=true
DRY_RUN=false
JEV_PRICE_PER_BILLION_INPUT=42
TRACE_DIR=traces
```
