---
description: Start the next Clev build phase
---

1. Read `docs/PROGRESS.md` and find the phase marked ⏳ Next. Resolve any open questions that block it
   (ask me if one needs my decision).
2. Read that phase in `CLEV_PLAN.md` §12, plus any sections it depends on.
3. Create a branch from an up-to-date `master` named `phase-<N>/<feature>` (see CLAUDE.md → Git workflow).
   Use separate `phase-<N>/fix-...` branches for fixes found later.
4. Briefly state the plan for the phase (files to add, tests to write), then build it following
   the rules in `CLAUDE.md`. Write tests alongside the code.
5. Run `uv run pytest -q` and `uv run ruff check .` until both pass.
6. Update `docs/PROGRESS.md`: mark the phase done, add a phase log entry, record deviations and
   open questions, and mark the following phase ⏳ Next.
7. Commit per section on the branch. Stop. Summarize what was built, how to run it, and what's unresolved. Wait for my confirmation.

$ARGUMENTS
