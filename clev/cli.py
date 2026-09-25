"""Command-line entry point: `clev run | observe | state | replay | eval`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from clev.config import DeciderName, Mode, load_settings
from clev.core.errors import ClevError
from clev.core.types import Element
from clev.state.match import find_same
from clev.trace.tracer import read_trace

app = typer.Typer(help="Clev: clever enough to know when to think.", no_args_is_help=True)


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="Natural-language task to perform.")],
    mode: Annotated[Mode, typer.Option(help="Where to act.")] = "browser",
    decider: Annotated[DeciderName | None, typer.Option(help="Override DECIDER.")] = None,
    url: Annotated[str | None, typer.Option(help="Page to open before planning.")] = None,
    dry_run: Annotated[
        bool | None, typer.Option("--dry-run/--no-dry-run", help="Print decisions only.")
    ] = None,
    max_steps: Annotated[int | None, typer.Option(help="Override MAX_STEPS.")] = None,
    headless: Annotated[bool | None, typer.Option("--headless/--headed")] = None,
    show_config: Annotated[bool, typer.Option(help="Print the parsed config and exit.")] = False,
) -> None:
    """Run a task: plan it, then observe -> decide -> act until done."""
    import asyncio

    settings = load_settings(
        decider=decider, dry_run=dry_run, max_steps=max_steps, headless=headless
    )
    if show_config:
        typer.echo(
            json.dumps({"task": task, "mode": mode, "config": settings.redacted()}, indent=2)
        )
        return
    if mode == "desktop":
        typer.echo("Desktop mode arrives in Phase 8.", err=True)
        raise typer.Exit(2)
    if settings.decider == "jev":
        typer.echo("The Jev decider arrives in Phase 5; use --decider llm or mock.", err=True)
        raise typer.Exit(2)
    try:
        ok = asyncio.run(_run(task, url, settings))
    except KeyboardInterrupt:
        typer.echo("\nStopped (Ctrl+C).", err=True)
        raise typer.Exit(130) from None
    raise typer.Exit(0 if ok else 1)


def make_llm(settings):
    """The configured LLMClient. Only clev/llm/ imports provider SDKs."""
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise typer.BadParameter("OPENAI_API_KEY is not set (see .env.example)")
        from clev.llm.openai import OpenAIClient

        return OpenAIClient(
            settings.openai_api_key.get_secret_value(),
            reasoning_effort=settings.llm_reasoning_effort,
            timeout_s=settings.llm_timeout_s,
        )
    raise typer.BadParameter(f"LLM_PROVIDER={settings.llm_provider} isn't implemented yet")


async def _run(task: str, url: str | None, settings) -> bool:
    import asyncio

    from clev.core.loop import Agent
    from clev.decide.llm_decider import LLMDecider
    from clev.decide.mock import MockDecider
    from clev.execute.browser import BrowserExecutor
    from clev.observe.browser import BrowserObserver, BrowserSession
    from clev.planner.planner import LLMPlanner
    from clev.safety.gate import SafetyGate
    from clev.trace.tracer import JsonlTracer

    llm = make_llm(settings)
    planner = LLMPlanner(llm, settings.planner_model)
    decider = (
        MockDecider() if settings.decider == "mock" else LLMDecider(llm, settings.escalation_model)
    )

    async def confirm(question: str) -> bool:
        return await asyncio.to_thread(typer.confirm, question, default=False)

    gate = SafetyGate(settings.confirm_destructive, settings.domain_allowlist, confirm)
    with JsonlTracer(settings.trace_dir) as tracer:
        async with BrowserSession(headless=settings.headless) as session:
            if url:
                await session.goto(url)
            agent = Agent(
                observer=BrowserObserver(session),
                executor=BrowserExecutor(session),
                decider=decider,
                planner=planner,
                gate=gate,
                tracer=tracer,
                settings=settings,
                run_id=tracer.run_id,
                on_event=typer.echo,
            )
            typer.echo(
                f"Task: {task}  (decider={settings.decider}, planner={settings.planner_model})"
            )
            result = await agent.run(task)
    typer.echo(
        f"\n{'SUCCESS' if result.success else 'FAILED'}: {result.reason}\n"
        f"steps={result.steps}  time={result.seconds:.1f}s  cost=${result.cost_usd:.4f}\n"
        f"trace: {tracer.path}"
    )
    return result.success


@app.command()
def replay(trace: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Print a trace step by step. (Rich rendering arrives in Phase 9.)"""
    for rec in read_trace(trace):
        d = rec.decision
        who = d.decided_by if d else "-"
        act = d.action.model_dump(exclude_none=True) if d else {}
        typer.echo(f"[{rec.step:>3}] {who:<4} {rec.subgoal!r} -> {act}")


def format_element(e: Element) -> str:
    flags = [f for f, on in (("disabled", not e.enabled), ("hidden", not e.visible),
                             ("focused", e.focused)) if on]  # fmt: skip
    line = f"{e.id:>6}  {e.role:<10} {e.name[:60]!r}"
    if e.value:
        line += f" = {e.value[:30]!r}"
    if e.context:
        line += f"  @ {e.context}"
    if flags:
        line += f"  [{', '.join(flags)}]"
    return line


@app.command()
def observe(
    url: Annotated[str, typer.Argument(help="Page to open.")],
    click: Annotated[str | None, typer.Option(help="Element id to act on, e.g. e12.")] = None,
    type_: Annotated[
        str | None, typer.Option("--type", help="Text to type into the --click element.")
    ] = None,
    press: Annotated[str | None, typer.Option(help="Key to press after, e.g. enter.")] = None,
    hold: Annotated[float, typer.Option(help="Seconds to keep the browser open at the end.")] = 0,
    save: Annotated[Path | None, typer.Option(help="Save observation (.json/.json.gz).")] = None,
    limit: Annotated[int, typer.Option(help="Max elements to print (0 = all).")] = 50,
    show_hidden: Annotated[bool, typer.Option(help="Also list hidden elements.")] = False,
    headless: Annotated[bool | None, typer.Option("--headless/--headed")] = None,
) -> None:
    """Open a page, list its elements, then optionally click, type into and press a key on one.

    Example: clev observe https://en.wikipedia.org --click e18 --type Karachi --press enter --headed
    """
    import asyncio

    if (type_ or press) and not click:
        raise typer.BadParameter("--type and --press need --click to pick the element")
    settings = load_settings(headless=headless)
    steps = ObserveSteps(click=click, text=type_, press=press, hold=hold)
    asyncio.run(_observe(url, steps, save, limit, show_hidden, settings.headless))


@dataclass
class ObserveSteps:
    click: str | None = None
    text: str | None = None
    press: str | None = None
    hold: float = 0


async def _observe(
    url: str, steps: ObserveSteps, save: Path | None, limit: int, show_hidden: bool, headless: bool
) -> None:
    # Imported lazily so other commands don't pay Playwright's import cost.
    from clev.core.types import Action
    from clev.execute.browser import BrowserExecutor
    from clev.observe.browser import BrowserObserver, BrowserSession
    from clev.observe.io import save_observation

    async with BrowserSession(headless=headless) as session:
        await session.goto(url)
        observer = BrowserObserver(session)
        obs = await observer.observe()
        shown = [e for e in obs.elements if show_hidden or e.visible]
        typer.echo(f"{obs.title} | {obs.url}")
        typer.echo(f"{len(obs.elements)} elements, {len(shown)} shown\n")
        for e in shown[: limit or None]:
            typer.echo(format_element(e))
        if limit and len(shown) > limit:
            typer.echo(f"   ... {len(shown) - limit} more (use --limit 0)")
        if save:
            save_observation(obs, save)
            typer.echo(f"\nSaved to {save}")
        if steps.click:
            target = obs.element(steps.click)
            if target is None:
                raise typer.BadParameter(f"No element {steps.click!r} in this observation")
            executor = BrowserExecutor(session)
            actions = [Action(kind="click")]
            if steps.text is not None:
                actions.append(Action(kind="type", text=steps.text))
            if steps.press:
                actions.append(Action(kind="key", key=steps.press))
            typer.echo(f"\nTarget {format_element(target).strip()}")
            for action in actions:
                # Pages often replace elements after an action (e.g. a search box turning into
                # a typeahead), so re-find the target in a fresh observation, like the loop will.
                if action.kind != "click":
                    obs = await observer.observe()
                    target = find_same(obs, target)
                    if target is None:
                        typer.echo("  target is gone after the previous action", err=True)
                        raise typer.Exit(1)
                action = action.model_copy(update={"element_id": target.id})
                typer.echo(f"  -> {action.kind} {target.id} {action.text or action.key or ''}")
                try:
                    await executor.execute(action, obs)
                except ClevError as e:
                    typer.echo(f"  failed: {e}", err=True)
                    raise typer.Exit(1) from e
            after = await observer.observe()
            typer.echo(f"Now at: {after.title} | {after.url} ({len(after.elements)} elements)")
            same_page = after.url.split("#")[0] == obs.url.split("#")[0]
            if steps.text is not None and same_page and (field := find_same(after, target)):
                typer.echo(f"Field now: {format_element(field).strip()}")
        if steps.hold:
            await session.page.wait_for_timeout(steps.hold * 1000)


@app.command()
def state(
    observation: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Saved .json(.gz)")
    ],
    goal: Annotated[str, typer.Argument(help="Current subgoal, e.g. 'Open the History section'.")],
    done: Annotated[list[str] | None, typer.Option(help="Completed subgoal (repeatable).")] = None,
    top: Annotated[int, typer.Option(help="Also print the N best-ranked options.")] = 5,
) -> None:
    """Show exactly what the decider sees for a saved observation and a subgoal."""
    from clev.observe.io import load_observation
    from clev.state.filter import filter_elements
    from clev.state.rank import rank
    from clev.state.serialize import build_state

    settings = load_settings()
    obs = load_observation(observation)
    st = build_state(obs, goal, done, settings.max_options, settings.token_budget)
    typer.echo(st.text)
    typer.echo(f"\n{len(st.options)} options, ~{st.token_estimate} tokens")
    if top:
        typer.echo(f"\nBest {top} by rank:")
        for e, score in rank(filter_elements(obs).candidates, goal, obs.viewport)[:top]:
            typer.echo(f"  {score:5.2f}  {format_element(e).strip()}")


@app.command(name="eval")
def eval_(benchmark: Annotated[str, typer.Argument(help="mind2web | webarena")]) -> None:
    """Run an evaluation. (Phases 6-7.)"""
    typer.echo(f"Eval '{benchmark}' not implemented yet.", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
