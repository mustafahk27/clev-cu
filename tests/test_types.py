from clev.core.interfaces import Decider, Executor, Observer, Planner, Tracer
from clev.core.types import (
    Action,
    Decision,
    Element,
    Observation,
    Option,
    SerializedState,
    StepRecord,
)


def make_obs() -> Observation:
    return Observation(
        app="chromium",
        title="Inbox",
        url="https://mail.example.com",
        elements=[
            Element(id="e1", role="button", name="Compose", context="Sidebar"),
            Element(id="e2", role="searchbox", name="Search mail", bounds=(0, 0, 100, 20)),
        ],
    )


def test_observation_lookup():
    obs = make_obs()
    assert obs.element("e2").role == "searchbox"
    assert obs.element("missing") is None


def test_step_record_json_roundtrip():
    obs = make_obs()
    rec = StepRecord(
        run_id="r1",
        step=0,
        subgoal="Open compose",
        observation=obs,
        decision=Decision(
            action=Action(kind="click", element_id="e1"),
            confidence=0.91,
            probs={"1": 0.91, "2": 0.09},
            decided_by="mock",
            chosen_label="1",
        ),
        checks={"subgoal_complete": 0.1},
    )
    again = StepRecord.model_validate_json(rec.model_dump_json())
    assert again == rec
    assert again.observation.elements[1].bounds == (0, 0, 100, 20)


def test_serialized_state_option_lookup():
    state = SerializedState(
        text='OPTIONS:\n 1 click button "Compose"',
        options=[
            Option(label="1", line='1 click button "Compose"', action=Action(kind="click")),
            Option(label="STUCK", line="STUCK"),
        ],
    )
    assert state.option("STUCK").action is None
    assert state.option("nope") is None


def test_protocols_are_structural():
    class FakeObserver:
        async def observe(self) -> Observation:
            return make_obs()

    class FakeDecider:
        async def decide(self, state, subgoal, history):
            raise NotImplementedError

        async def check(self, state, question):
            return 0.5

    class FakePlanner:
        async def plan(self, task, obs):
            return []

        async def write_text(self, task, subgoal, field):
            return ""

        async def replan(self, task, done, obs, reason):
            return []

        cost_usd = 0.0

    class FakeExecutor:
        async def execute(self, action, obs):
            return None

    class FakeTracer:
        def record(self, step):
            pass

        def close(self):
            pass

    assert isinstance(FakeObserver(), Observer)
    assert isinstance(FakeDecider(), Decider)
    assert isinstance(FakePlanner(), Planner)
    assert isinstance(FakeExecutor(), Executor)
    assert isinstance(FakeTracer(), Tracer)
    assert not isinstance(object(), Observer)
