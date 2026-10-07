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
from medialab_setup.gitops import GitError
from medialab_setup.preflight import PreflightError
from medialab_setup.prompts import NonInteractiveError, QuestionaryPrompter
from medialab_setup.report import answers_table, files_table
from medialab_setup.scripts import ScriptError
from medialab_setup.setup_flow import (
    LAST_PHASE,
    Phase,
    SetupContext,
    SetupOptions,
    VerifyError,
    run_setup,
)
from medialab_setup.shell import Shell
from medialab_setup.update_flow import (
    RolledBack,
    UpdateContext,
    UpdateError,
    UpdateOptions,
    run_update,
)
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
SkipHostOption = Annotated[bool, typer.Option("--skip-host", help="Skip the host autostart steps.")]
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
    stop_after: StopAfterOption = LAST_PHASE,
    yes: YesOption = False,
    skip_host: SkipHostOption = False,
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
            skip_host=skip_host,
        ),
        shell=make_shell(),
        prompter=QuestionaryPrompter(console),
        checker=CredentialChecker(),
        console=console,
    )
    try:
        run_setup(ctx)
    except (CollectError, NonInteractiveError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_USAGE) from error
    except (PreflightError, ScriptError, VerifyError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_FAILURE) from error


ToOption = Annotated[
    str | None, typer.Option("--to", help="Root ref to move to (default: origin/main).")
]
NoRollbackOption = Annotated[
    bool, typer.Option("--no-rollback", help="Leave the new state in place when verify fails.")
]
EXIT_ROLLED_BACK = 3


@app.command()
def update(
    workspace: WorkspaceOption = None,
    to: ToOption = None,
    dry_run: DryRunOption = False,
    no_rollback: NoRollbackOption = False,
) -> None:
    """Move a running stack to the current pins: check, snapshot, fetch, migrate, build, verify."""
    ws = find_workspace(workspace)
    ctx = UpdateContext(
        workspace=ws,
        options=UpdateOptions(
            to=to, dry_run=dry_run, rollback=not no_rollback, interactive=sys.stdin.isatty()
        ),
        shell=make_shell(),
        prompter=QuestionaryPrompter(console),
        console=console,
    )
    try:
        run_update(ctx)
    except RolledBack as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_ROLLED_BACK) from error
    except (UpdateError, GitError, ScriptError, CollectError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(EXIT_FAILURE) from error


WIZARD_HOST = "127.0.0.1"
WIZARD_POLL_SECONDS = 1.0
PortOption = Annotated[int, typer.Option("--port", help="Loopback port; 0 picks a free one.")]
NoBrowserOption = Annotated[
    bool, typer.Option("--no-browser", help="Print the URL instead of opening the browser.")
]


@app.command()
def wizard(
    workspace: WorkspaceOption = None,
    port: PortOption = 0,
    no_browser: NoBrowserOption = False,
) -> None:
    """Open the browser-based installer; exits when you close it or after idling."""
    import socket
    import threading
    import time
    import webbrowser

    import uvicorn

    from medialab_setup.wizard.app import WizardState, create_app, should_stop

    ws = find_workspace(workspace)
    state = WizardState(workspace=ws, shell=make_shell(), checker=CredentialChecker())
    if port == 0:
        with socket.socket() as probe:
            probe.bind((WIZARD_HOST, 0))
            port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(state), host=WIZARD_HOST, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="medialab-setup-wizard", daemon=True)
    thread.start()
    url = f"http://{WIZARD_HOST}:{port}/?t={state.token}"
    console.print(f"Setup is open at {url}")
    if not no_browser:
        webbrowser.open(url)
    try:
        while not should_stop(state):
            time.sleep(WIZARD_POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    thread.join()
