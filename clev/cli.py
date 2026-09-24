"""Command-line entry point: `clev run`, `clev observe`, `clev replay`, `clev eval`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from clev.config import DeciderName, Mode, load_settings
from clev.core.types import Element
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
    click: Annotated[str | None, typer.Option(help="Element id to click, e.g. e12.")] = None,
    save: Annotated[Path | None, typer.Option(help="Save observation (.json/.json.gz).")] = None,
    limit: Annotated[int, typer.Option(help="Max elements to print (0 = all).")] = 50,
    show_hidden: Annotated[bool, typer.Option(help="Also list hidden elements.")] = False,
    headless: Annotated[bool | None, typer.Option("--headless/--headed")] = None,
) -> None:
    """Open a page, list its elements, and optionally click one by id."""
    import asyncio

    settings = load_settings(headless=headless)
    asyncio.run(_observe(url, click, save, limit, show_hidden, settings.headless))


async def _observe(
    url: str, click: str | None, save: Path | None, limit: int, show_hidden: bool, headless: bool
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
        if click:
            target = obs.element(click)
            if target is None:
                raise typer.BadParameter(f"No element {click!r} in this observation")
            typer.echo(f"\nClicking {format_element(target).strip()}")
            await BrowserExecutor(session).execute(Action(kind="click", element_id=click), obs)
            after = await observer.observe()
            typer.echo(f"Now at: {after.title} | {after.url} ({len(after.elements)} elements)")


@app.command(name="eval")
def eval_(benchmark: Annotated[str, typer.Argument(help="mind2web | webarena")]) -> None:
    """Run an evaluation. (Phases 6-7.)"""
    typer.echo(f"Eval '{benchmark}' not implemented yet.", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
