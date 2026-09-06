"""CLI operations consume Core directly; terminal imports are lazy."""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import json
import typer
from s4code.core.application import S4CodeRuntime
from s4code.core.configuration import S4ConfigLoader
from s4code.core.sessions.session import CoreSession
from s4code.core.configuration import dump_settings_yaml
from s4code.core.workflows import ReviewWorkflow, CommitWorkflow

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    help="S4Code: local software engineering Agent.",
)
session_app = typer.Typer(help="Session management.")
app.add_typer(session_app, name="session")


def _run(session: CoreSession, prompt: str):
    result = session.run(prompt)
    if result.status == "interaction_required":
        session.save()
        typer.echo(
            json.dumps(
                {
                    "status": "interaction_required",
                    "session_id": session.id,
                    "interaction": result.interaction.model_dump(mode="json"),
                },
                ensure_ascii=False,
                default=str,
            )
        )
        raise typer.Exit(code=2)
    typer.echo(result.text)
    if result.status != "completed":
        raise typer.Exit(code=1)


@app.callback()
def main(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p"),
    resume: Optional[str] = typer.Option(None, "--resume"),
    cwd: Path = typer.Option(Path("."), "--cwd"),
):
    if ctx.invoked_subcommand is not None:
        return
    if prompt is None:
        from s4code.interfaces.terminal.controller import TerminalController
        from s4code.interfaces.textual.app import S4TextualApp

        controller = TerminalController(cwd=cwd, session_id=resume)
        try:
            S4TextualApp(controller).run()
        finally:
            controller.close()
        return
    with S4CodeRuntime(cwd=cwd) as runtime:
        _run(runtime.open_session(resume), prompt)


@app.command()
def review(
    target: Optional[str] = typer.Argument(None),
    cwd: Path = typer.Option(Path("."), "--cwd"),
):
    with S4CodeRuntime(cwd=cwd) as runtime:
        _run(runtime.open_session(), ReviewWorkflow().prompt(target))


@app.command()
def commit(cwd: Path = typer.Option(Path("."), "--cwd")):
    with S4CodeRuntime(cwd=cwd) as runtime:
        _run(runtime.open_session(), CommitWorkflow().prompt())


@app.command("config")
def show_config(cwd: Path = typer.Option(Path("."), "--cwd")):
    typer.echo(dump_settings_yaml(S4ConfigLoader().load_agent_settings(cwd)))


@app.command()
def doctor(cwd: Path = typer.Option(Path("."), "--cwd")):
    with S4CodeRuntime(cwd=cwd) as runtime:
        typer.echo(
            json.dumps(
                runtime.open_session().diagnostics(),
                ensure_ascii=False,
            )
        )


@session_app.command("list")
def session_list(cwd: Path = typer.Option(Path("."), "--cwd")):
    with S4CodeRuntime(cwd=cwd) as runtime:
        typer.echo(
            json.dumps(
                [item.model_dump(mode="json") for item in runtime.list_sessions()],
                ensure_ascii=False,
            )
        )
