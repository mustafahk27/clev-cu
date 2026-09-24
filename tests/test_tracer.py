import json

from clev.core.types import Observation, StepRecord
from clev.trace.tracer import JsonlTracer, read_trace


def test_tracer_writes_one_line_per_step(tmp_path):
    obs = Observation(app="chromium", title="t")
    with JsonlTracer(tmp_path / "traces", run_id="run1") as tracer:
        for i in range(3):
            tracer.record(StepRecord(run_id="run1", step=i, subgoal="g", observation=obs))
        path = tracer.path

    lines = path.read_text().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[2])["step"] == 2
    assert [r.step for r in read_trace(path)] == [0, 1, 2]


def test_tracer_flushes_before_close(tmp_path):
    tracer = JsonlTracer(tmp_path)
    tracer.record(
        StepRecord(
            run_id=tracer.run_id, step=0, subgoal="g", observation=Observation(app="a", title="t")
        )
    )
    assert len(list(read_trace(tracer.path))) == 1
    tracer.close()
