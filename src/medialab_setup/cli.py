"""Command tree. Each command wires phases together; the phases live in their modules."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from medialab_setup.checks import CredentialChecker
from medialab_setup.collect import CollectError, Mode, collect
from medialab_setup.generate import render_all
from medialab_setup.prompts import NonInteractiveError, QuestionaryPrompter
from medialab_setup.report import answers_table, files_table
from medialab_setup.workspace import COMPOSE_FILE, Workspace

PACKAGE_NAME = "medialab-setup"
VERSION_UNKNOWN = "unknown"
EXIT_USAGE = 2

app = typer.Typer(
    name=PACKAGE_NAME,
    help="Install and update the medialab stack from a clone of the workspace.",
    no_args_is_help=True,
)
console = Console()

WorkspaceOption = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        help=f"Workspace root (the directory holding {COMPOSE_FILE}). Default: search upward.",
    ),
]
CustomOption = Annotated[
    bool, typer.Option("--custom/--express", help="Ask every value, or only the required ones.")
]
AnswersOption = Annotated[
    Path | None, typer.Option("--answers", help="Replay non-secret answers from this TOML file.")
]


@app.callback()
def main() -> None:
    """Install and update the medialab stack from a clone of the workspace."""


def installed_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return VERSION_UNKNOWN


def find_workspace(start: Path | None) -> Workspace:
    if start is not None:
        return Workspace(start.resolve())
    for candidate in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        if (candidate / COMPOSE_FILE).exists():
            return Workspace(candidate)
    raise typer.BadParameter(f"no {COMPOSE_FILE} found from {Path.cwd()} upward; pass --workspace")


@app.command("version")
def version_cmd() -> None:
    """Print the tool version."""
    typer.echo(installed_version())


@app.command()
def plan(
    workspace: WorkspaceOption = None,
    custom: CustomOption = False,
    answers: AnswersOption = None,
) -> None:
    """Collect answers and show what setup would write, writing nothing."""
    ws = find_workspace(workspace)
    try:
        collected = collect(
            ws,
            mode=Mode.CUSTOM if custom else Mode.EXPRESS,
            prompter=QuestionaryPrompter(console),
            checker=CredentialChecker(),
            answers_file=answers,
            interactive=sys.stdin.isatty(),
        )
    except (CollectError, NonInteractiveError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_USAGE) from error
    rendered = render_all(ws, collected.answers)
    console.print(answers_table(collected))
    console.print(files_table(ws, rendered))
    for warning in collected.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")
    console.print("Dry run: nothing was written.")
