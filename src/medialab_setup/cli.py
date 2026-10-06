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
from medialab_setup.preflight import PreflightError
from medialab_setup.prompts import NonInteractiveError, QuestionaryPrompter
from medialab_setup.report import answers_table, files_table
from medialab_setup.setup_flow import (
    IMPLEMENTED_THROUGH,
    NotImplementedPhase,
    Phase,
    SetupContext,
    SetupOptions,
    run_setup,
)
from medialab_setup.shell import Shell
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
DryRunOption = Annotated[bool, typer.Option("--dry-run", help="Show the plan; write nothing.")]
StopAfterOption = Annotated[
    Phase, typer.Option("--stop-after", help="Last phase to run.", case_sensitive=False)
]
YesOption = Annotated[bool, typer.Option("--yes", help="Confirm every install step.")]
EXIT_FAILURE = 1

# Replaced in tests so no real process, port or disk is touched.
make_shell = Shell


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


@app.command()
def setup(
    workspace: WorkspaceOption = None,
    custom: CustomOption = False,
    answers: AnswersOption = None,
    dry_run: DryRunOption = False,
    stop_after: StopAfterOption = IMPLEMENTED_THROUGH,
    yes: YesOption = False,
) -> None:
    """Take a fresh clone to a configured stack: preflight, collect, generate, and on."""
    ws = find_workspace(workspace)
    ctx = SetupContext(
        workspace=ws,
        options=SetupOptions(
            mode=Mode.CUSTOM if custom else Mode.EXPRESS,
            answers_file=answers,
            dry_run=dry_run,
            stop_after=stop_after,
            assume_yes=yes,
            interactive=sys.stdin.isatty(),
        ),
        shell=make_shell(),
        prompter=QuestionaryPrompter(console),
        checker=CredentialChecker(),
        console=console,
    )
    try:
        run_setup(ctx)
    except NotImplementedPhase as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_USAGE) from error
    except (CollectError, NonInteractiveError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_USAGE) from error
    except PreflightError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_FAILURE) from error
