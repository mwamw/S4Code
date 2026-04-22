"""Typer CLI entrypoint for S4Code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .commands import register_builtin_commands
from .query_engine import S4QueryEngine
from .tui import S4TextualApp


app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    help="S4Code: a local-first code agent CLI built on EasyAgent.",
)
session_app = typer.Typer(help="Session management commands.")
app.add_typer(session_app, name="session")
console = Console()


def _build_engine(
    *,
    cwd: Path,
    session_id: Optional[str] = None,
) -> S4QueryEngine:
    engine = S4QueryEngine(cwd=cwd, session_id=session_id)
    register_builtin_commands(engine.command_registry)
    return engine


@app.callback()
def main(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Run a single prompt and exit."),
    resume: Optional[str] = typer.Option(None, "--resume", help="Resume an existing session."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory / repository root."),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    engine = _build_engine(cwd=cwd.resolve(), session_id=resume)
    if prompt:
        console.print(engine.run_prompt(prompt))
        return
    S4TextualApp(engine).run()


@app.command("review")
def review(
    target: Optional[str] = typer.Argument(None, help="Optional diff target."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory / repository root."),
) -> None:
    engine = _build_engine(cwd=cwd.resolve())
    console.print(engine.run_prompt(engine.build_review_prompt(target)))


@app.command("commit")
def commit(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory / repository root."),
) -> None:
    engine = _build_engine(cwd=cwd.resolve())
    console.print(engine.run_prompt(engine.build_commit_prompt()))


@app.command("config")
def show_config(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory / repository root."),
) -> None:
    engine = _build_engine(cwd=cwd.resolve())
    console.print(engine.format_config())


@app.command("doctor")
def doctor(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory / repository root."),
) -> None:
    engine = _build_engine(cwd=cwd.resolve())
    payload = {
        "project": engine.project.to_status_dict(),
        "status": json.loads(engine.format_status()),
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


@session_app.command("list")
def session_list(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory / repository root."),
) -> None:
    engine = _build_engine(cwd=cwd.resolve())
    console.print(engine.format_sessions())
