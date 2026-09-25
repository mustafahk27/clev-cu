"""Render the ranked candidates as the numbered option list deciders see (plan §7)."""

from __future__ import annotations

import math

from clev.core.types import Action, Element, Observation, Option, SerializedState, StepRecord
from clev.state.filter import filter_elements
from clev.state.rank import is_editable, rank, select

# (label, line shown to the decider, action). Actions of None are control signals for the loop.
GLOBAL_OPTIONS: list[tuple[str, str, Action | None]] = [
    ("SCROLL_DOWN", "scroll down", Action(kind="scroll", direction="down")),
    ("SCROLL_UP", "scroll up", Action(kind="scroll", direction="up")),
    ("GO_BACK", "go back", Action(kind="back")),
    ("WAIT", "wait for the page", Action(kind="wait")),
    ("PRESS_ENTER", "press Enter (submit the focused field)", Action(kind="key", key="enter")),
    ("SUBGOAL_DONE", "the current goal is already achieved", None),
    ("NONE_OF_THESE", "none of these options fit", None),
    ("STUCK", "stuck, need help", None),
]
CHARS_PER_TOKEN = 3.5  # conservative estimate for English + UI labels
NAME_CAP = 100  # always
NAME_CAP_TIGHT = 60  # when over budget (plan §7)
CONTEXT_TAGS = {"heading": "h", "alert": "alert", "status": "status"}


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def element_line(label: str, e: Element, name_cap: int = NAME_CAP) -> str:
    verb = "type" if is_editable(e) else "click"
    line = f"{label:>3} {verb} {e.role} {clip(e.name, name_cap)!r}"
    if e.value:
        line += f" = {clip(e.value, 40)!r}"
    if e.focused:
        line += " [focused]"
    if e.context:
        line += f" @ {e.context}"
    return line


def element_action(e: Element) -> Action:
    # "type" text is filled in by the loop (subgoal literal or planner.write_text).
    return Action(kind="type" if is_editable(e) else "click", element_id=e.id)


def header(obs: Observation, subgoal: str, done: list[str], context: list[Element]) -> str:
    url = (obs.url or "").split("://", 1)[-1]
    lines = [f"APP: {obs.app} | TITLE: {clip(obs.title, 100)} | URL: {clip(url, 120)}"]
    lines.append(f"GOAL: {subgoal}")
    done_text = " ".join(f"{i}) {d}" for i, d in enumerate(done, 1)) if done else "(nothing yet)"
    lines.append(f"DONE SO FAR: {done_text}")
    if context:
        parts = [f"[{CONTEXT_TAGS[e.role]}] {clip(e.name, 80)}" for e in context]
        lines.append("CONTEXT: " + " | ".join(parts))
    lines.append("OPTIONS:")
    return "\n".join(lines)


def build_state(
    obs: Observation,
    subgoal: str,
    done: list[str] | None = None,
    max_options: int = 200,
    token_budget: int = 24000,
) -> SerializedState:
    """Filter, rank, keep the top `max_options`, and render within `token_budget` tokens.

    Options are listed in page order (reads like the screen); ranking only decides which make
    the cut, with a reserve spread across the page (see `select`). Over budget: first tighten
    names to 60 chars, then drop options from the end of the priority list.
    """
    filtered = filter_elements(obs)
    order = {e.id: i for i, e in enumerate(obs.elements)}
    ranked = [e for e, _ in rank(filtered.candidates, subgoal, obs.viewport)]
    keep = select(ranked, max_options, order)
    head = header(obs, subgoal, done or [], filtered.context)

    name_cap = NAME_CAP
    while True:
        chosen = sorted(keep, key=lambda e: order[e.id])
        options = [
            Option(label=str(i), line=element_line(str(i), e, name_cap), action=element_action(e))
            for i, e in enumerate(chosen, 1)
        ]
        options += [Option(label=lab, line=f"{lab:>3} {text}", action=act)
                    for lab, text, act in GLOBAL_OPTIONS]  # fmt: skip
        text = head + "\n" + "\n".join(o.line for o in options)
        tokens = estimate_tokens(text)
        if tokens <= token_budget or (not keep and name_cap == NAME_CAP_TIGHT):
            elements = {str(i): e for i, e in enumerate(chosen, 1)}
            return SerializedState(
                text=text, options=options, token_estimate=tokens, elements=elements
            )
        if name_cap != NAME_CAP_TIGHT:
            name_cap = NAME_CAP_TIGHT
        else:
            keep = keep[: max(0, len(keep) - max(1, len(keep) // 10))]  # drop worst 10%


def describe_action(
    action: Action | None, obs: Observation | None, label: str | None = None
) -> str:
    """Human-readable action for history and logs, e.g. "type searchbox 'Search' = 'Muscat'"."""
    if action is None:
        return label or "(no action)"
    target = obs.element(action.element_id) if obs and action.element_id else None
    what = f"{target.role} {clip(target.name, 60)!r}" if target else (action.element_id or "")
    match action.kind:
        case "type":
            return f"type {what} = {clip(action.text or '', 40)!r}"
        case "key":
            return f"press {action.key}" + (f" on {what}" if target else "")
        case "scroll":
            return f"scroll {action.direction or 'down'}"
        case "goto":
            return f"open {action.url}"
        case "click":
            return f"click {what}"
        case _:
            return action.kind


def history_lines(history: list[StepRecord], limit: int = 6) -> list[str]:
    """The last few executed or attempted steps, oldest first, with their outcome."""
    lines = []
    for rec in [r for r in history if r.event == "step" and r.decision][-limit:]:
        d = rec.decision
        outcome = "ok"
        if rec.error:
            outcome = f"failed: {clip(rec.error, 80)}"
        elif rec.blocked_by_safety:
            outcome = f"blocked: {rec.blocked_by_safety}"
        elif not rec.executed and d.action is not None:
            outcome = "not executed"
        lines.append(f"- {describe_action(d.action, rec.observation, d.chosen_label)} -> {outcome}")
    return lines
