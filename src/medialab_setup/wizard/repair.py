"""The wizard's fix flow: replace one credential, recreate its container, verify via health.

No build, no provision, no doctor: the existing collect, generate and compose
pieces are called as functions for the one key that changed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import IO, cast

from medialab_contracts import CredentialStatus
from pydantic import SecretStr
from rich.console import Console

from medialab_setup.bindings import BINDINGS, owner_of
from medialab_setup.credential_check import (
    GATEWAY_HEALTH_URL,
    HEALTH_CREDENTIALS_KEY,
    read_gateway_credentials,
)
from medialab_setup.generate import collect_existing, render_all, write_all
from medialab_setup.guides import guide_for
from medialab_setup.scripts import ScriptError, compose_up_command, run_or_raise
from medialab_setup.shell import Shell
from medialab_setup.wizard.runner import LOG_WIDTH, Run, RunState
from medialab_setup.workspace import Workspace

REPAIR_VERIFY_ATTEMPTS = 20
REPAIR_VERIFY_INTERVAL_SECONDS = 6


class RepairError(RuntimeError):
    """The replaced credential did not come back as ok."""


def owning_service(name: str) -> str:
    owner = owner_of(name, BINDINGS)
    if owner is None:
        raise RepairError(f"{name} is not a credential this tool knows")
    return owner.target


def repair(
    workspace: Workspace, shell: Shell, name: str, value: str, log_note: Callable[[str], object]
) -> None:
    """Write the one key, recreate its container, poll the gateway until it reads ok."""
    guide = guide_for(name)
    service = owning_service(name)
    answers = collect_existing(workspace, BINDINGS).with_generated()
    typed = SecretStr(value) if guide.secret else value
    answers = answers.model_copy(update={name: typed})
    rendered = render_all(workspace, answers, BINDINGS)
    changed = write_all(workspace, rendered)
    log_note(f"Wrote {len(changed)} file(s) for {guide.title}.")
    command = [*compose_up_command(workspace), service]
    log_note(f"$ {' '.join(command)}")
    run_or_raise(shell, command, f"docker compose up {service}")
    for attempt in range(1, REPAIR_VERIFY_ATTEMPTS + 1):
        states = read_gateway_credentials(shell)
        state = states.get(name) if states else None
        if state is not None and state.status is CredentialStatus.OK:
            log_note(f"{guide.title} accepted by its service.")
            return
        if state is not None and state.status is CredentialStatus.INVALID and attempt > 1:
            raise RepairError(f"{guide.title} is still rejected: {state.detail}")
        log_note(f"Waiting for {guide.title} to report ok ({attempt}/{REPAIR_VERIFY_ATTEMPTS}).")
        shell.sleep(REPAIR_VERIFY_INTERVAL_SECONDS)
    raise RepairError(f"{guide.title} did not report ok within the verify window")


def start_repair(
    workspace: Workspace, shell: Shell, name: str, value: str, *, in_thread: bool = True
) -> Run:
    run = Run()
    run.state = RunState.RUNNING

    def work() -> None:
        console = Console(
            file=cast(IO[str], run.log), force_terminal=False, width=LOG_WIDTH, highlight=False
        )
        shell.output_sink = run.log.append
        try:
            repair(workspace, shell, name, value, console.print)
            run.state = RunState.SUCCEEDED
        except (RepairError, ScriptError) as error:
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
        run.thread = threading.Thread(target=work, name="medialab-setup-repair", daemon=True)
        run.thread.start()
    else:
        work()
    return run


__all__ = [
    "GATEWAY_HEALTH_URL",
    "HEALTH_CREDENTIALS_KEY",
    "RepairError",
    "json",
    "owning_service",
    "repair",
    "start_repair",
]
