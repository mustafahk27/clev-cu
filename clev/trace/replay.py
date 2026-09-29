"""Read traces back as text: per-step lines and a run summary (who decided, escalations, time)."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from clev.core.types import StepRecord
from clev.state.serialize import describe_action


def step_line(rec: StepRecord) -> str:
    if rec.event == "plan":
        return f"[plan] {rec.note or ''}\n       " + "\n       ".join(
            f"{i}. {s}" for i, s in enumerate(rec.subgoals or [], 1)
        )
    if rec.event == "replan":
        return f"[replan] {rec.note}: " + " | ".join(rec.subgoals or [])
    if rec.event == "end":
        return f"[end] {rec.note}  (total ${rec.cost_usd:.4f}, {rec.latency_ms / 1000:.1f}s)"
    d = rec.decision
    if d is None:
        return f"[{rec.step:>3}] -"
    what = describe_action(d.action, rec.observation, d.chosen_label)
    conf = f" p={d.confidence:.2f}" if d.decided_by == "jev" else ""
    head = f"[{rec.step:>3}] {d.decided_by:<4}{conf} {d.latency_ms:6.0f}ms"
    line = f"{head}  {rec.subgoal[:45]!r} -> {what}"
    if d.escalated:
        jev = (
            f"jev had {d.primary_choice} p={d.primary_confidence:.2f}; " if d.primary_choice else ""
        )
        line += f"\n       escalated: {jev}{d.escalation_reason}"
    elif d.escalation_reason:
        line += f"  ({d.escalation_reason})"
    if rec.error:
        line += f"\n       error: {rec.error}"
    if rec.blocked_by_safety:
        line += f"\n       blocked: {rec.blocked_by_safety}"
    return line


@dataclass
class Summary:
    steps: int = 0
    decided_by: Counter = field(default_factory=Counter)
    escalations: list[str] = field(default_factory=list)
    latency_ms: dict[str, list[float]] = field(default_factory=dict)
    cost_usd: float = 0.0
    seconds: float = 0.0
    result: str = ""

    @property
    def escalation_rate(self) -> float:
        return len(self.escalations) / self.steps if self.steps else 0.0

    def lines(self) -> list[str]:
        who = ", ".join(f"{k}={v}" for k, v in sorted(self.decided_by.items()))
        out = [
            f"result: {self.result}",
            f"steps: {self.steps} ({who})  escalation rate: {self.escalation_rate:.0%}",
        ]
        for kind, values in sorted(self.latency_ms.items()):
            out.append(f"{kind} decision latency: median {statistics.median(values):.0f} ms")
        for reason, n in Counter(self.escalations).most_common():
            out.append(f"  escalated x{n}: {reason}")
        out.append(f"time: {self.seconds:.1f}s  cost: ${self.cost_usd:.4f}")
        return out


def summarize(records: list[StepRecord]) -> Summary:
    s = Summary()
    for rec in records:
        if rec.event == "end":
            s.result, s.cost_usd, s.seconds = rec.note or "", rec.cost_usd, rec.latency_ms / 1000
        if rec.event != "step" or rec.decision is None:
            continue
        d = rec.decision
        s.steps += 1
        s.decided_by[d.decided_by] += 1
        s.latency_ms.setdefault(d.decided_by, []).append(d.latency_ms)
        if d.escalated:
            s.escalations.append(_reason_kind(d.escalation_reason or ""))
    return s


def _reason_kind(reason: str) -> str:
    """Group reasons with numbers in them ("low confidence 0.41 < 0.6" -> "low confidence")."""
    for prefix in ("low confidence", "top two options", "jev error", "jev chose"):
        if reason.startswith(prefix):
            return reason if prefix == "jev chose" else prefix
    return reason
