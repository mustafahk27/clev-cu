"""Phase 1 performance benchmark: overhead the skeleton adds to every step.

Context: Jev decides in ~70-500ms per step, so per-step bookkeeping (building types, tracing)
should stay in the low milliseconds even on large pages.

Run: uv run python benchmarks/bench_phase1.py
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from clev.config import Settings
from clev.core.types import Action, Decision, Observation, StepRecord
from clev.trace.tracer import JsonlTracer, read_trace

ROLES = ["button", "link", "textbox", "checkbox", "menuitem", "tab", "heading", "text"]
SIZES = [100, 1000, 5000]  # small page, typical app, heavy page (e.g. Gmail / Amazon)
REPEATS = 20


def timeit(fn, repeats: int = REPEATS) -> tuple[float, float]:
    """Return (median_ms, p95_ms) over `repeats` runs."""
    samples = []
    for _ in range(repeats):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(0.95 * (len(samples) - 1))]


def raw_elements(n: int) -> list[dict]:
    return [
        {
            "id": f"e{i}",
            "role": ROLES[i % len(ROLES)],
            "name": f"Element number {i} with a realistic accessible label",
            "value": None if i % 3 else f"value {i}",
            "context": "Main > Section > Toolbar",
            "enabled": True,
            "focused": i == 0,
            "visible": i % 5 != 0,
            "bounds": (i % 1200, i // 10, 120, 24),
        }
        for i in range(n)
    ]


def step_record(obs: Observation, step: int) -> StepRecord:
    return StepRecord(
        run_id="bench",
        step=step,
        subgoal="Open the compose window",
        observation=obs,
        decision=Decision(
            action=Action(kind="click", element_id="e1"),
            confidence=0.9,
            probs={str(i): 1 / 200 for i in range(200)},  # full option distribution
            decided_by="mock",
        ),
        checks={"subgoal_complete": 0.1, "error_visible": 0.02, "progress": 0.4},
    )


def row(label: str, med: float, p95: float, extra: str = "") -> None:
    print(f"  {label:<38} median {med:8.2f} ms   p95 {p95:8.2f} ms   {extra}")


def bench_cli() -> None:
    print("CLI / startup")
    env = {**os.environ, "DECIDER": "mock"}
    cmd = [sys.executable, "-m", "clev.cli", "run", "bench task"]
    med, p95 = timeit(lambda: subprocess.run(cmd, capture_output=True, env=env, check=True), 5)
    row("clev run (cold process, end to end)", med, p95)
    imp = [sys.executable, "-c", "import clev.cli"]
    med, p95 = timeit(lambda: subprocess.run(imp, capture_output=True, check=True), 5)
    row("python + import clev.cli", med, p95)
    med, p95 = timeit(Settings)
    row("Settings() load", med, p95)


def bench_trace() -> None:
    for n in SIZES:
        print(f"\nObservation with {n} elements")
        raw = raw_elements(n)
        med, p95 = timeit(lambda raw=raw: Observation(app="chromium", title="t", elements=raw))
        row("build + validate Observation", med, p95)

        obs = Observation(app="chromium", title="t", elements=raw)
        rec = step_record(obs, 0)
        med, p95 = timeit(rec.model_dump_json)
        size_kb = len(rec.model_dump_json()) / 1024
        row("StepRecord -> JSON", med, p95, f"{size_kb:,.0f} KB/step")

        with tempfile.TemporaryDirectory() as d:
            tracer = JsonlTracer(Path(d), run_id="bench")
            counter = iter(range(10**6))
            med, p95 = timeit(lambda t=tracer, o=obs, c=counter: t.record(step_record(o, next(c))))
            row("tracer.record (build + write + flush)", med, p95)
            tracer.close()

            steps = sum(1 for _ in read_trace(tracer.path))
            t = time.perf_counter()
            list(read_trace(tracer.path))
            per = (time.perf_counter() - t) * 1000 / steps
            mb_50 = size_kb * 50 / 1024
            print(
                f"  {'read_trace per step':<38} {per:8.2f} ms   "
                f"(50-step run = {mb_50:,.1f} MB trace)"
            )


if __name__ == "__main__":
    print(f"Python {sys.version.split()[0]}, {REPEATS} repeats (5 for subprocess)\n")
    bench_cli()
    bench_trace()
