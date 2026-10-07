"""Runs the CLI phases in a background thread, writing to a LineLog the page polls."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import IO, cast

from rich.console import Console

from medialab_setup.checks import CredentialChecker
from medialab_setup.collect import CollectError, Mode
from medialab_setup.jellyfin_client import JellyfinClient
from medialab_setup.preflight import PreflightError
from medialab_setup.scripts import ScriptError
from medialab_setup.setup_flow import (
    Phase,
    SetupContext,
    SetupOptions,
    VerifyError,
    run_build,
    run_collect,
    run_generate,
    run_provision,
    run_verify,
)
from medialab_setup.shell import Shell
from medialab_setup.wizard.log import LineLog
from medialab_setup.wizard.prompter import WebPrompter
from medialab_setup.workspace import Workspace

LOG_WIDTH = 100
RUN_PHASES: tuple[Phase, ...] = (
    Phase.COLLECT,
    Phase.GENERATE,
    Phase.BUILD,
    Phase.PROVISION,
    Phase.VERIFY,
)
RUNNERS = {
    Phase.COLLECT: run_collect,
    Phase.GENERATE: run_generate,
    Phase.BUILD: run_build,
    Phase.PROVISION: run_provision,
    Phase.VERIFY: run_verify,
}


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Run:
    log: LineLog = field(default_factory=LineLog)
    state: RunState = RunState.IDLE
    phase: Phase | None = None
    error: str | None = None
    thread: threading.Thread | None = None

    @property
    def finished(self) -> bool:
        return self.state in (RunState.SUCCEEDED, RunState.FAILED)


def start_run(
    workspace: Workspace,
    shell: Shell,
    checker: CredentialChecker,
    form: dict[str, str],
    *,
    in_thread: bool = True,
    make_jellyfin_client: type[JellyfinClient] = JellyfinClient,
) -> Run:
    run = Run()
    run.state = RunState.RUNNING

    def work() -> None:
        sink = cast(IO[str], run.log)
        console = Console(file=sink, force_terminal=False, width=LOG_WIDTH, highlight=False)
        shell.output_sink = run.log.append
        ctx = SetupContext(
            workspace=workspace,
            options=SetupOptions(mode=Mode.CUSTOM, interactive=True),
            shell=shell,
            prompter=WebPrompter(form, run.log),
            checker=checker,
            console=console,
            make_jellyfin_client=make_jellyfin_client,
        )
        try:
            for phase in RUN_PHASES:
                run.phase = phase
                console.rule(phase.value)
                RUNNERS[phase](ctx)
            run.state = RunState.SUCCEEDED
        except (CollectError, PreflightError, ScriptError, VerifyError) as error:
            run.error = str(error)
            run.state = RunState.FAILED
            run.log.append(f"error: {error}")
        except Exception as error:  # noqa: BLE001 - a background thread must never die silently
            run.error = f"unexpected error: {error}"
            run.state = RunState.FAILED
            run.log.append(run.error)
        finally:
            run.log.flush()
            shell.output_sink = None

    if in_thread:
        run.thread = threading.Thread(target=work, name="medialab-setup-run", daemon=True)
        run.thread.start()
    else:
        work()
    return run
