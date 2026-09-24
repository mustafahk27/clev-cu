"""Command-line entry point: `clev run`, `clev replay`, `clev eval`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from clev.config import DeciderName, Mode, load_settings
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


@app.command(name="eval")
def eval_(benchmark: Annotated[str, typer.Argument(help="mind2web | webarena")]) -> None:
    """Run an evaluation. (Phases 6-7.)"""
    typer.echo(f"Eval '{benchmark}' not implemented yet.", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
