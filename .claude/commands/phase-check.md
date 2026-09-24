---
description: Check the current phase against its "Done when" criteria
---

1. From `docs/PROGRESS.md`, identify the current phase (the latest one done or in progress).
2. Quote its **Done when** criteria from `CLEV_PLAN.md` §12.
3. Verify each one with real commands (`uv run pytest -q`, `uv run ruff check .`, the CLI or
   scripts the criterion names). Show the output. Don't claim anything passes without running it.
4. Report each criterion as pass/fail with evidence, and list any gaps. Don't fix anything
   unless I ask.
