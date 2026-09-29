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


def make_decider(settings, llm):
    """(decider, jev) for DECIDER=mock|llm|jev. `jev` is returned so its client can be closed."""
    from clev.decide.llm_decider import LLMDecider
    from clev.decide.mock import MockDecider

    if settings.decider == "mock":
        return MockDecider(), None
    fallback = LLMDecider(llm, settings.escalation_model)
    if settings.decider == "llm":
        return fallback, None
    if not settings.jev_api_key:
        raise typer.BadParameter("JEV_API_KEY is not set (see .env.example)")
    from clev.decide.escalate import EscalatingDecider, Policy
    from clev.decide.jev import JevDecider, make_client

    jev = JevDecider(
        make_client(
            settings.jev_api_key.get_secret_value(),
            settings.jev_base_url,
            settings.jev_model,
            settings.jev_timeout_s,
        ),
        settings.jev_price_per_billion_input,
    )
    policy = Policy(
        confidence_threshold=settings.confidence_threshold,
        margin=settings.margin,
        done_threshold=settings.done_threshold,
        error_threshold=settings.error_threshold,
    )
    return EscalatingDecider(jev, fallback, policy), jev


async def _run(task: str, url: str | None, settings) -> bool:
    import asyncio

    from clev.core.loop import Agent
    from clev.execute.browser import BrowserExecutor
    from clev.observe.browser import BrowserObserver, BrowserSession
    from clev.planner.planner import LLMPlanner
    from clev.safety.gate import SafetyGate
    from clev.trace.tracer import JsonlTracer

    llm = make_llm(settings)
    planner = LLMPlanner(llm, settings.planner_model)
    decider, jev = make_decider(settings, llm)

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
            deciding = settings.decider + (
                f" ({settings.jev_model}, LLM fallback {settings.escalation_model})"
                if settings.decider == "jev"
                else ""
            )
            typer.echo(f"Task: {task}  (decider={deciding}, planner={settings.planner_model})")
            try:
                result = await agent.run(task)
            finally:
                if jev is not None:
                    await jev.aclose()
    from clev.trace.replay import summarize
    from clev.trace.tracer import read_trace

    typer.echo(f"\n{'SUCCESS' if result.success else 'FAILED'}: {result.reason}")
    for line in summarize(list(read_trace(tracer.path))).lines()[1:]:
        typer.echo(line)
    typer.echo(f"trace: {tracer.path}")
    return result.success


@app.command()
def replay(trace: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Print a trace step by step, then a summary: who decided, escalations, latency, cost."""
    from clev.trace.replay import step_line, summarize

    records = list(read_trace(trace))
    for rec in records:
        typer.echo(step_line(rec))
    typer.echo("")
    for line in summarize(records).lines():
        typer.echo(line)


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
def eval_(
    benchmark: Annotated[str, typer.Argument(help="mind2web (webarena arrives in Phase 7)")],
    n: Annotated[int, typer.Option(help="Steps to evaluate.")] = 500,
    llms: Annotated[str, typer.Option(help="Comma-separated LLM baselines.")] = "",
    jev_options: Annotated[str, typer.Option(help="Option counts to run Jev at.")] = "50,100,200",
    concurrency: Annotated[int, typer.Option(help="Parallel model calls.")] = 8,
    seed: Annotated[int, typer.Option(help="Sampling seed.")] = 0,
    out: Annotated[Path | None, typer.Option(help="Report directory.")] = None,
    planned: Annotated[
        bool, typer.Option(help="Also run the live-style variant (planner writes subgoals).")
    ] = True,
) -> None:
    """Offline step-level eval: Jev alone, Jev + escalation, and LLM-only baselines."""
    import asyncio
    import time

    if benchmark != "mind2web":
        typer.echo(f"Eval '{benchmark}' not implemented yet (webarena: Phase 7).", err=True)
        raise typer.Exit(1)
    try:
        from evals.mind2web.run import run_all
        from evals.report import Policy, write_report
    except ImportError as e:
        raise typer.BadParameter(f"eval extras missing ({e}); run: uv sync --extra eval") from e

    settings = load_settings()
    models = [m.strip() for m in (llms or f"{settings.escalation_model},gpt-6-sol").split(",") if m]
    if settings.escalation_model not in models:
        models.insert(0, settings.escalation_model)  # needed to simulate escalation
    counts = sorted({int(k) for k in jev_options.split(",") if k.strip()} | {settings.max_options})
    runs = [("jev", k) for k in counts] + [(m, settings.max_options) for m in models]
    out = out or Path("evals/results") / f"mind2web-{time.strftime('%Y%m%d-%H%M%S')}"

    async def main():
        from clev.decide.jev import JevDecider, make_client
        from clev.decide.llm_decider import LLMDecider

        if not settings.jev_api_key:
            raise typer.BadParameter("JEV_API_KEY is not set")
        client = make_client(
            settings.jev_api_key.get_secret_value(),
            settings.jev_base_url,
            settings.jev_model,
            settings.jev_timeout_s,
        )
        llm = make_llm(settings)
        jev = JevDecider(client, settings.jev_price_per_billion_input)
        try:
            prepared, results = await run_all(
                n,
                runs,
                lambda name: jev if name == "jev" else LLMDecider(llm, name),
                concurrency,
                seed,
                typer.echo,
            )
            plan_results = None
            if planned:
                from evals.mind2web.planned import run_planned
                from evals.mind2web.run import load_cache

                fallback = LLMDecider(llm, settings.escalation_model)
                plan_results = await run_planned(
                    prepared,
                    llm,
                    settings.planner_model,
                    {"jev": jev, settings.escalation_model: fallback},
                    settings.max_options,
                    load_cache(),
                    concurrency,
                    typer.echo,
                )
            return prepared, results, plan_results
        finally:
            await jev.aclose()

    prepared, results, plan_results = asyncio.run(main())
    policy = Policy(
        settings.confidence_threshold,
        settings.margin,
        settings.done_threshold,
        settings.error_threshold,
    )
    write_report(
        out,
        prepared,
        results,
        settings.escalation_model,
        policy,
        settings.max_options,
        plan_results,
    )
    typer.echo(f"\nReport: {out / 'report.md'}")
    typer.echo((out / "report.md").read_text().split("## Pipeline ceiling")[0])


if __name__ == "__main__":
    app()
