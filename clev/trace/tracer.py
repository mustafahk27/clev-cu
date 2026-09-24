"""JSONL tracer: one StepRecord per line, so every run can be replayed and re-analyzed."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from clev.core.types import StepRecord


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class JsonlTracer:
    def __init__(self, trace_dir: Path, run_id: str | None = None):
        self.run_id = run_id or new_run_id()
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.path = trace_dir / f"{self.run_id}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")

    def record(self, step: StepRecord) -> None:
        self._fh.write(step.model_dump_json() + "\n")
        self._fh.flush()  # a crash mid-run should still leave a usable trace

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> JsonlTracer:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_trace(path: Path) -> Iterator[StepRecord]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield StepRecord.model_validate_json(line)
