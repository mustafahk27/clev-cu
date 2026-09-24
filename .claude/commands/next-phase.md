---
description: Start the next Clev build phase
---

1. Read `docs/PROGRESS.md` and find the phase marked ⏳ Next. Resolve any open questions that block it
   (ask me if one needs my decision).
2. Read that phase in `CLEV_PLAN.md` §12, plus any sections it depends on.
3. Briefly state the plan for the phase (files to add, tests to write), then build it following
   the rules in `CLAUDE.md`. Write tests alongside the code.
4. Run `uv run pytest -q` and `uv run ruff check .` until both pass.
5. Update `docs/PROGRESS.md`: mark the phase done, add a phase log entry, record deviations and
   open questions, and mark the following phase ⏳ Next.
6. Stop. Summarize what was built, how to run it, and what's unresolved. Wait for my confirmation.

$ARGUMENTS
