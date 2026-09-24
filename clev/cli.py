"""Command-line entry point: `clev run`, `clev observe`, `clev replay`, `clev eval`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from clev.config import DeciderName, Mode, load_settings
from clev.core.errors import ClevError
from clev.core.types import Element, Observation
from clev.trace.tracer import read_trace

app = typer.Typer(help="Clev: clever enough to know when to think.", no_args_is_help=True)


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="Natural-language task to perform.")],
    mode: Annotated[Mode, typer.Option(help="Where to act.")] = "browser",
    decider: Annotated[DeciderName | None, typer.Option(help="Override DECIDER.")] = None,
    dry_run: Annotated[
        bool | None, typer.Option("--dry-run/--no-dry-run", help="Print decisions only.")
    ] = None,
    max_steps: Annotated[int | None, typer.Option(help="Override MAX_STEPS.")] = None,
) -> None:
    """Run a task. (Phase 1: prints the parsed config; the loop arrives in Phase 4.)"""
    settings = load_settings(decider=decider, dry_run=dry_run, max_steps=max_steps)
    typer.echo(json.dumps({"task": task, "mode": mode, "config": settings.redacted()}, indent=2))
    typer.echo("Control loop not implemented yet (Phase 4).", err=True)


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


def find_same(obs: Observation, old: Element) -> Element | None:
    """Find `old` in a newer observation.

    Widgets change role when activated (Wikipedia's searchbox becomes a combobox on focus), so
    match by name, preferring the focused element and then the same role, else the focused one.
    """
    same_name = [e for e in obs.elements if e.name == old.name]
    for e in same_name:
        if e.focused:
            return e
    for e in same_name:
        if e.role == old.role:
            return e
    return next((e for e in obs.elements if e.focused), same_name[0] if same_name else None)


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


@app.command(name="eval")
def eval_(benchmark: Annotated[str, typer.Argument(help="mind2web | webarena")]) -> None:
    """Run an evaluation. (Phases 6-7.)"""
    typer.echo(f"Eval '{benchmark}' not implemented yet.", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
