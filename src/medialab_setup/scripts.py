"""Drive the workspace's bin/ scripts and compose through Git's bash and docker."""

from __future__ import annotations

from pathlib import Path

from medialab_setup.shell import Shell
from medialab_setup.workspace import ENV_FILE, Workspace

GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = "bash"
BUILD_SCRIPT = "bin/medialab-build.sh"
PROVISION_SCRIPT = "bin/medialab-qbt-provision.sh"
DOCTOR_SCRIPT = "bin/medialab-doctor.sh"
VERSIONS_FILE = ".versions.env"


class ScriptError(RuntimeError):
    """A bin/ script or compose exited non-zero."""


def bash_executable(shell: Shell) -> str:
    """Git's bash, never WSL's: the scripts assume Git Bash path handling."""
    if shell.path_exists(GIT_BASH):
        return str(GIT_BASH)
    found = shell.which(BASH)
    if found is None:
        raise ScriptError("Git Bash not found; install Git for Windows")
    return found


def script_command(shell: Shell, workspace: Workspace, script: str, *args: str) -> list[str]:
    return [bash_executable(shell), str(workspace.root / script), *args]


def compose_up_command(workspace: Workspace) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(workspace.root),
        "--env-file",
        str(workspace.root / ENV_FILE),
        "--env-file",
        str(workspace.root / VERSIONS_FILE),
        "up",
        "-d",
    ]


def run_or_raise(shell: Shell, command: list[str], what: str) -> None:
    code = shell.stream(command)
    if code != 0:
        raise ScriptError(f"{what} exited {code}")
