"""The setup command: phases in order, each a function, stopping at the first failure."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx
from medialab_contracts import MEDIA_TYPE_SUBDIRS, STAGING_SUBDIR
from rich.console import Console
from rich.table import Table

from medialab_setup.answers_file import answers_path, write_answers
from medialab_setup.checks import CredentialChecker
from medialab_setup.collect import Collected, Mode, collect
from medialab_setup.generate import render_all, write_all
from medialab_setup.host import HostPhase, HostRow
from medialab_setup.jellyfin_client import JellyfinClient, ensure_library_roots
from medialab_setup.preflight import Preflight, PreflightError, PreflightResult, Status
from medialab_setup.prompts import Prompter, UrlOpener, open_in_browser
from medialab_setup.report import answers_table, files_table
from medialab_setup.scripts import (
    BUILD_SCRIPT,
    DOCTOR_SCRIPT,
    PROVISION_SCRIPT,
    VERIFY_WINDOW_SECONDS,
    ScriptError,
    compose_up_command,
    run_or_raise,
    script_command,
    wait_for_doctor,
)
from medialab_setup.shell import Shell
from medialab_setup.workspace import Workspace

MINIMUM_FREE_BYTES = 50 * 1024**3


class Phase(str, Enum):
    PREFLIGHT = "preflight"
    COLLECT = "collect"
    GENERATE = "generate"
    BUILD = "build"
    PROVISION = "provision"
    HOST = "host"
    VERIFY = "verify"


PHASE_ORDER: tuple[Phase, ...] = tuple(Phase)
LAST_PHASE = PHASE_ORDER[-1]


class VerifyError(RuntimeError):
    """The doctor never went green inside the verify window."""


@dataclass(frozen=True)
class SetupOptions:
    mode: Mode = Mode.EXPRESS
    answers_file: Path | None = None
    dry_run: bool = False
    stop_after: Phase = LAST_PHASE
    assume_yes: bool = False
    interactive: bool = True
    skip_host: bool = False


@dataclass
class SetupContext:
    workspace: Workspace
    options: SetupOptions
    shell: Shell
    prompter: Prompter
    checker: CredentialChecker
    console: Console
    opener: UrlOpener = open_in_browser
    collected: Collected | None = None
    make_jellyfin_client: type[JellyfinClient] = JellyfinClient


def media_folders(media_host_dir: str) -> list[Path]:
    root = Path(media_host_dir)
    library = [root / name for name in MEDIA_TYPE_SUBDIRS.values()]
    staging = [root / STAGING_SUBDIR / name for name in MEDIA_TYPE_SUBDIRS.values()]
    return [*library, *staging]


def preflight_table(result: PreflightResult) -> Table:
    table = Table(title="Preflight")
    table.add_column("")
    table.add_column("Check")
    table.add_column("Detail")
    for row in result.rows:
        table.add_row(row.status.value, row.name, row.detail)
    return table


def run_preflight(ctx: SetupContext) -> None:
    result = Preflight(
        ctx.workspace,
        ctx.shell,
        ctx.prompter,
        assume_yes=ctx.options.assume_yes,
        interactive=ctx.options.interactive,
        opener=ctx.opener,
    ).run()
    ctx.console.print(preflight_table(result))
    if result.failed:
        failed = [row.name for row in result.rows if row.status is Status.FAIL]
        raise PreflightError(f"preflight failed: {', '.join(failed)}")


def run_collect(ctx: SetupContext) -> None:
    ctx.collected = collect(
        ctx.workspace,
        mode=ctx.options.mode,
        prompter=ctx.prompter,
        checker=ctx.checker,
        answers_file=ctx.options.answers_file,
        interactive=ctx.options.interactive,
        opener=ctx.opener,
    )
    ctx.console.print(answers_table(ctx.collected))
    for warning in ctx.collected.warnings:
        ctx.console.print(f"[yellow]warning:[/yellow] {warning}")


def run_generate(ctx: SetupContext) -> None:
    if ctx.collected is None:
        raise RuntimeError("generate needs collect")
    answers = ctx.collected.answers
    rendered = render_all(ctx.workspace, answers)
    ctx.console.print(files_table(ctx.workspace, rendered))
    folders = media_folders(answers.media_host_dir) if answers.media_host_dir else []
    if folders:
        free = ctx.shell.disk_free_bytes(folders[0].parent)
        if free < MINIMUM_FREE_BYTES:
            ctx.console.print(
                f"[yellow]warning:[/yellow] {free // 1024**3} GiB free on the media drive"
            )
    if ctx.options.dry_run:
        ctx.console.print("Dry run: nothing was written.")
        return
    changed = write_all(ctx.workspace, rendered)
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
    write_answers(answers_path(ctx.workspace.root), answers, backup_dir=ctx.workspace.backup_dir)
    ctx.console.print(
        f"Wrote {len(changed)} file(s); media folders present under {answers.media_host_dir}."
    )


def _announce(ctx: SetupContext, command: list[str]) -> None:
    ctx.console.print(f"$ {' '.join(command)}")


def run_build(ctx: SetupContext) -> None:
    command = script_command(ctx.shell, ctx.workspace, BUILD_SCRIPT)
    _announce(ctx, command)
    if ctx.options.dry_run:
        return
    run_or_raise(ctx.shell, command, BUILD_SCRIPT)


def run_provision(ctx: SetupContext) -> None:
    provision = script_command(ctx.shell, ctx.workspace, PROVISION_SCRIPT)
    up = compose_up_command(ctx.workspace)
    _announce(ctx, provision)
    _announce(ctx, up)
    answers = ctx.collected.answers if ctx.collected else None
    if ctx.options.dry_run:
        ctx.console.print("Would register the Movies and Shows library roots in Jellyfin.")
        return
    run_or_raise(ctx.shell, provision, PROVISION_SCRIPT)
    run_or_raise(ctx.shell, up, "docker compose up")
    if answers is None or not answers.media_host_dir or answers.jellyfin_api_key is None:
        ctx.console.print("[yellow]warning:[/yellow] Jellyfin libraries not registered: no key")
        return
    client = ctx.make_jellyfin_client(answers.jellyfin_api_key.get_secret_value())
    try:
        created = ensure_library_roots(client, answers.media_host_dir)
    except httpx.HTTPError as error:
        raise ScriptError(f"Jellyfin library registration failed: {error}") from error
    if created:
        ctx.console.print(f"Jellyfin libraries created: {', '.join(created)}")
    else:
        ctx.console.print("Jellyfin libraries present.")


def host_table(rows: list[HostRow]) -> Table:
    table = Table(title="Host")
    table.add_column("")
    table.add_column("Step")
    table.add_column("Detail")
    for row in rows:
        table.add_row(row.outcome.value, row.name, row.detail)
    return table


def run_host(ctx: SetupContext) -> None:
    rows = HostPhase(
        ctx.workspace,
        ctx.shell,
        ctx.prompter,
        dry_run=ctx.options.dry_run,
        assume_yes=ctx.options.assume_yes,
        interactive=ctx.options.interactive,
        opener=ctx.opener,
    ).run()
    ctx.console.print(host_table(rows))


def run_verify(ctx: SetupContext) -> None:
    if ctx.options.dry_run:
        ctx.console.print(f"$ {' '.join(script_command(ctx.shell, ctx.workspace, DOCTOR_SCRIPT))}")
        return
    if not wait_for_doctor(ctx.shell, ctx.workspace, ctx.console.print):
        raise VerifyError(f"doctor still failing after {VERIFY_WINDOW_SECONDS} s")


PHASE_RUNNERS = {
    Phase.PREFLIGHT: run_preflight,
    Phase.COLLECT: run_collect,
    Phase.GENERATE: run_generate,
    Phase.BUILD: run_build,
    Phase.PROVISION: run_provision,
    Phase.HOST: run_host,
    Phase.VERIFY: run_verify,
}


def run_setup(ctx: SetupContext) -> None:
    stop_index = PHASE_ORDER.index(ctx.options.stop_after)
    for phase in PHASE_ORDER[: stop_index + 1]:
        ctx.console.rule(phase.value)
        if phase is Phase.HOST and ctx.options.skip_host:
            ctx.console.print("Skipped (--skip-host).")
            continue
        PHASE_RUNNERS[phase](ctx)
