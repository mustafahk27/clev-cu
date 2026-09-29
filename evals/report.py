"""Metrics, escalation simulation, calibration and plots for step-level evals."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from evals.mind2web.run import Answer, Prepared

CONTROL = {"SUBGOAL_DONE", "NONE_OF_THESE", "STUCK"}


# --- per-step scoring --------------------------------------------------------------------


def element_ok(a: Answer, p: Prepared, strict: bool = False) -> bool:
    return (
        a.error is None
        and a.element_id is not None
        and (a.element_id in (p.strict if strict else p.equivalent))
    )


def action_ok(a: Answer, p: Prepared) -> bool:
    """Right element and right verb (TYPE -> type; CLICK/SELECT/HOVER -> click)."""
    return element_ok(a, p) and a.verb == p.step.expected_verb


@dataclass
class Row:
    name: str
    n: int
    element_acc: float  # equivalent-element match, all steps
    element_acc_strict: float
    element_acc_answerable: float  # steps whose target exists in the saved HTML
    action_acc: float
    escalation_rate: float
    latency_median_ms: float
    latency_p95_ms: float
    cost_per_step: float
    errors: int

    def cells(self) -> list[str]:
        return [
            self.name,
            f"{self.element_acc:.1%}",
            f"{self.element_acc_strict:.1%}",
            f"{self.element_acc_answerable:.1%}",
            f"{self.action_acc:.1%}",
            f"{self.escalation_rate:.0%}" if self.escalation_rate else "–",
            f"{self.latency_median_ms:,.0f}",
            f"{self.latency_p95_ms:,.0f}",
            f"${self.cost_per_step * 1000:.3f}",
            str(self.errors),
        ]


HEADER = [
    "Decider", "Element acc", "strict", "answerable", "Action acc", "Escalated",
    "Median ms", "p95 ms", "$ / 1k steps", "Errors",
]  # fmt: skip


def _p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else 0.0


@dataclass
class Outcome:
    """What the system did on one step (after any escalation)."""

    answer: Answer | None  # the answer that was acted on (None: control signal, no action)
    latency_ms: float
    cost_usd: float
    escalated: bool
    error: bool = False


def row_from_outcomes(name: str, outcomes: list[Outcome], prepared: list[Prepared]) -> Row:
    n = len(prepared)
    answerable = [i for i, p in enumerate(prepared) if p.target_in_html]
    ok = [
        o.answer is not None and element_ok(o.answer, p)
        for o, p in zip(outcomes, prepared, strict=True)
    ]
    strict = [
        o.answer is not None and element_ok(o.answer, p, strict=True)
        for o, p in zip(outcomes, prepared, strict=True)
    ]
    act = [
        o.answer is not None and action_ok(o.answer, p)
        for o, p in zip(outcomes, prepared, strict=True)
    ]
    lat = [o.latency_ms for o in outcomes]
    return Row(
        name=name,
        n=n,
        element_acc=sum(ok) / n,
        element_acc_strict=sum(strict) / n,
        element_acc_answerable=sum(ok[i] for i in answerable) / max(1, len(answerable)),
        action_acc=sum(act) / n,
        escalation_rate=sum(o.escalated for o in outcomes) / n,
        latency_median_ms=statistics.median(lat),
        latency_p95_ms=_p95(lat),
        cost_per_step=sum(o.cost_usd for o in outcomes) / n,
        errors=sum(o.error for o in outcomes),
    )


def plain(answers: list[Answer]) -> list[Outcome]:
    return [
        Outcome(
            a if a.label not in CONTROL else None, a.latency_ms, a.cost_usd, False, bool(a.error)
        )
        for a in answers
    ]


# --- Jev + escalation, simulated from recorded answers --------------------------------------


@dataclass(frozen=True)
class Policy:
    threshold: float = 0.6
    margin: float = 0.1
    done_threshold: float = 0.7
    error_threshold: float = 0.7


def escalate_outcomes(jev: list[Answer], llm: list[Answer], policy: Policy) -> list[Outcome]:
    """Per-step version of clev.decide.escalate (history rules don't apply offline).

    A high subgoal_complete / error_visible check would end the subgoal / replan live; offline
    that step's action is simply not taken, so it scores as wrong.
    """
    out = []
    for j, fb in zip(jev, llm, strict=True):

        def to_llm(j=j, fb=fb):
            return Outcome(
                fb if fb.label not in CONTROL else None,
                j.latency_ms + fb.latency_ms,
                j.cost_usd + fb.cost_usd,
                True,
                bool(fb.error),
            )

        if j.error:
            out.append(to_llm())
        elif j.checks.get("error_visible", 0) > policy.error_threshold or (
            j.checks.get("subgoal_complete", 0) > policy.done_threshold
        ):
            out.append(Outcome(None, j.latency_ms, j.cost_usd, False))
        elif (
            j.label in ("NONE_OF_THESE", "STUCK")
            or (j.confidence or 0) < policy.threshold
            or (j.margin is not None and j.margin < policy.margin)
        ):
            out.append(to_llm())
        else:
            out.append(
                Outcome(j if j.label not in CONTROL else None, j.latency_ms, j.cost_usd, False)
            )
    return out


def with_planner(outcomes: list[Outcome], plans: list[Answer]) -> list[Outcome]:
    """Charge each step for the planner call that wrote its subgoal."""
    return [
        Outcome(
            o.answer, o.latency_ms + pl.latency_ms, o.cost_usd + pl.cost_usd, o.escalated, o.error
        )  # fmt: skip
        for o, pl in zip(outcomes, plans, strict=True)
    ]


# --- calibration -------------------------------------------------------------------------


@dataclass
class Bin:
    lo: float
    hi: float
    n: int
    confidence: float
    accuracy: float


def calibration(
    jev: list[Answer], prepared: list[Prepared], bins: int = 10
) -> tuple[list[Bin], float]:
    pairs = [
        (a.confidence, element_ok(a, p))
        for a, p in zip(jev, prepared, strict=True)
        if a.error is None and a.confidence is not None
    ]
    out, ece = [], 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(c, ok) for c, ok in pairs if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if not inside:
            continue
        conf = sum(c for c, _ in inside) / len(inside)
        acc = sum(ok for _, ok in inside) / len(inside)
        out.append(Bin(lo, hi, len(inside), conf, acc))
        ece += len(inside) / len(pairs) * abs(acc - conf)
    return out, ece


# --- plots -------------------------------------------------------------------------------


def plot_reliability(bins: list[Bin], ece: float, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="#999", label="perfect calibration")
    ax.bar([b.lo for b in bins], [b.accuracy for b in bins], width=0.1, align="edge",
           color="#4C72B0", alpha=0.8, edgecolor="white", label="accuracy")  # fmt: skip
    ax.plot([b.confidence for b in bins], [b.accuracy for b in bins], "o", color="#C44E52",
            label="accuracy at bin mean confidence")  # fmt: skip
    for b in bins:
        ax.text(b.lo + 0.05, min(0.97, b.accuracy + 0.02), str(b.n), ha="center", fontsize=7)
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Jev confidence", ylabel="element accuracy",
           title=f"Jev next_action calibration (ECE {ece:.3f})")  # fmt: skip
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_sweep(points: list[dict], baselines: dict[str, float], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = [p["threshold"] for p in points]
    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    ax1.plot(t, [p["accuracy"] for p in points], "-o", ms=3, color="#4C72B0", label="Clev accuracy")
    ax1.plot(t, [p["escalation_rate"] for p in points], "-s", ms=3, color="#DD8452",
             label="escalation rate")  # fmt: skip
    for (name, acc), color in zip(
        baselines.items(), ["#55A868", "#8172B3", "#937860"], strict=False
    ):
        ax1.axhline(acc, ls=":", color=color, label=f"{name} alone")
    ax1.set(xlabel="CONFIDENCE_THRESHOLD", ylabel="rate", ylim=(0, 1))
    ax2 = ax1.twinx()
    ax2.plot(t, [p["cost_per_step"] * 1000 for p in points], "-^", ms=3, color="#C44E52",
             label="$ / 1k steps")  # fmt: skip
    ax2.set_ylabel("$ per 1,000 steps")
    lines = ax1.get_legend_handles_labels()
    lines2 = ax2.get_legend_handles_labels()
    ax1.legend(lines[0] + lines2[0], lines[1] + lines2[1], fontsize=7, loc="lower right")
    ax1.set_title("Jev + escalation: accuracy vs escalation vs cost")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --- report ------------------------------------------------------------------------------


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])


def write_report(
    out: Path,
    prepared: list[Prepared],
    results: dict[tuple[str, int], list[Answer]],
    escalation_model: str,
    policy: Policy,
    default_options: int = 200,
    planned: tuple[list[Answer], dict[str, list[Answer]]] | None = None,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    n = len(prepared)
    jev = results.get(("jev", default_options))
    llm = results.get((escalation_model, default_options))

    rows: list[Row] = []
    if jev and llm:
        rows.append(row_from_outcomes(
            f"**Clev** (Jev + {escalation_model} @ {policy.threshold})",
            escalate_outcomes(jev, llm, policy), prepared,
        ))  # fmt: skip
    for (name, k), answers in results.items():
        if k == default_options:
            label = "Jev alone" if name == "jev" else f"{name} alone (LLM-only baseline)"
            rows.append(row_from_outcomes(label, plain(answers), prepared))

    options_rows = [
        row_from_outcomes(f"Jev alone, {k} options", plain(a), prepared)
        for (name, k), a in sorted(results.items(), key=lambda kv: kv[0][1])
        if name == "jev"
    ]

    sweep = []
    if jev and llm:
        from dataclasses import replace

        for i in range(0, 21):
            t = i / 20
            outcomes = escalate_outcomes(jev, llm, replace(policy, threshold=t))
            r = row_from_outcomes("", outcomes, prepared)
            sweep.append(
                {
                    "threshold": t,
                    "accuracy": r.element_acc,
                    "escalation_rate": r.escalation_rate,
                    "cost_per_step": r.cost_per_step,
                    "latency_median_ms": r.latency_median_ms,
                }
            )
        baselines = {
            name: row_from_outcomes(name, plain(a), prepared).element_acc
            for (name, k), a in results.items()
            if k == default_options and name != "jev"
        }
        plot_sweep(sweep, baselines, out / "threshold_sweep.png")

    bins, ece = calibration(jev, prepared) if jev else ([], 0.0)
    if bins:
        plot_reliability(bins, ece, out / "reliability.png")

    in_html = sum(p.target_in_html for p in prepared)
    observed = sum(p.observed for p in prepared)
    in_opts = {
        k: sum(bool({o.action.element_id for o in p.states[k].options if o.action} & p.equivalent)
               for p in prepared)
        for k in sorted({k for _, k in results})
    }  # fmt: skip
    tokens = [
        p.states[default_options].token_estimate for p in prepared if default_options in p.states
    ]

    md = [
        f"# Mind2Web step-level eval ({n} steps)",
        "",
        f"Steps sampled evenly from the first shard of each official test split "
        f"(task / website / domain), {len({p.step.website for p in prepared})} websites, "
        f"{len({p.step.task for p in prepared})} tasks. Every decider sees the same Clev pipeline "
        "output (observer -> filter -> rank -> 200 options), so only the decider differs.",
        "",
        "## Headline",
        "",
        _table(HEADER, [r.cells() for r in rows]),
        "",
        "- **Element acc**: chose the target element or one that clicks the same thing (its label, "
        "or a link wrapping it). **strict**: exact Mind2Web element. **answerable**: only steps "
        "whose target exists in Mind2Web's saved HTML. **Action acc**: right element and right "
        "verb (TYPE -> type; CLICK/SELECT/HOVER -> click). Typed values aren't scored.",
        "- Latency is per decision (network included), cost is per step, both from real API usage.",
        "",
        "## Pipeline ceiling (before any decider)",
        "",
        _table(
            ["Stage", "Steps", "Share"],
            [
                ["Target exists in Mind2Web's saved HTML", str(in_html), f"{in_html / n:.1%}"],
                [
                    "Observer sees it (or an equivalent element)",
                    str(observed),
                    f"{observed / n:.1%}",
                ],
                *[
                    [f"Target among the {k} options", str(v), f"{v / n:.1%}"]
                    for k, v in in_opts.items()
                ],
            ],
        ),  # fmt: skip
        "",
        f"Serialized state size: median {statistics.median(tokens):,.0f} tokens, "
        f"max {max(tokens):,} (budget 24,000).",
    ]
    planned_rows: list[Row] = []
    if planned:
        plans, pres = planned
        pj, pl = pres.get("jev+plan"), pres.get(f"{escalation_model}+plan")
        if pj and pl:
            planned_rows.append(row_from_outcomes(
                f"**Clev + planner** (Jev + {escalation_model} @ {policy.threshold})",
                with_planner(escalate_outcomes(pj, pl, policy), plans), prepared,
            ))  # fmt: skip
        for name, answers in pres.items():
            label = name.replace("+plan", "") + " + planner"
            planned_rows.append(
                row_from_outcomes(label, with_planner(plain(answers), plans), prepared)
            )
        pbins, pece = calibration(pj, prepared) if pj else ([], 0.0)
        examples = [
            f'- *{p.step.task[:90]}* -> "{plan.subgoal}"'
            for p, plan in zip(prepared[:5], plans[:5], strict=True)
        ]
        planner_model = plans[0].decider.split(":", 1)[1]
        md_planned = [
            "",
            "## Live-style: planner writes the next subgoal, then the decider picks",
            "",
            "Mind2Web gives the decider the whole task, so above it must plan *and* pick. Live "
            "Clev splits those: the planner writes short subgoals and Jev picks elements. Here the "
            f"real planner (`LLMPlanner.replan`, {planner_model}) writes each step's next subgoal "
            "from the task, past actions and page; every decider gets the same subgoal. "
            "Latency and cost include that planner call (live Clev plans once per task, so this "
            "overstates both).",
            "",
            _table(HEADER, [r.cells() for r in planned_rows]),
            "",
            f"Jev calibration with planner subgoals: ECE {pece:.3f}.",
            "",
            "Example subgoals:",
            *examples,
        ]
    if len(options_rows) > 1:
        md += ["", "## Jev by option count", "", _table(HEADER, [r.cells() for r in options_rows])]
    if bins:
        md += [
            "",
            f"## Calibration of Jev's next_action confidence (ECE {ece:.3f})",
            "",
            "![reliability](reliability.png)",
            "",
            _table(
                ["Confidence", "Steps", "Mean confidence", "Accuracy"],
                [
                    [f"{b.lo:.1f}–{b.hi:.1f}", str(b.n), f"{b.confidence:.2f}", f"{b.accuracy:.1%}"]
                    for b in bins
                ],
            ),  # fmt: skip
        ]
    if sweep:
        md += [
            "",
            "## CONFIDENCE_THRESHOLD sweep (Jev + escalation, simulated from recorded answers)",
            "",
            "![sweep](threshold_sweep.png)",
            "",
            _table(
                ["Threshold", "Accuracy", "Escalated", "$ / 1k steps", "Median ms"],
                [
                    [
                        f"{p['threshold']:.2f}",
                        f"{p['accuracy']:.1%}",
                        f"{p['escalation_rate']:.0%}",
                        f"${p['cost_per_step'] * 1000:.3f}",
                        f"{p['latency_median_ms']:,.0f}",
                    ]
                    for p in sweep
                    if round(p["threshold"] * 20) % 2 == 0
                ],
            ),  # fmt: skip
        ]
    if planned_rows:
        at = md.index("## Pipeline ceiling (before any decider)")
        md[at:at] = md_planned[1:] + [""]
    (out / "report.md").write_text("\n".join(md) + "\n")
    summary = {
        "n": n,
        "rows": [r.__dict__ for r in rows],
        "options": [r.__dict__ for r in options_rows],
        "planned": [r.__dict__ for r in planned_rows],
        "ece": ece,
        "sweep": sweep,
        "ceiling": {"in_html": in_html, "observed": observed, "in_options": in_opts},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
