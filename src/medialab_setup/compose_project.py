"""Who owns the compose project this workspace would run as.

A compose project is identified by name, not by directory. `docker-compose.yml`
sets `name:`, so two clones of the workspace share one project: `up` in the
second clone takes over the first clone's containers and named volumes. The
tool refuses to run compose when the project already belongs to another
directory. `COMPOSE_PROJECT_NAME` overrides the file's name, which is how a
scratch clone gets a project of its own.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from medialab_setup.shell import Shell
from medialab_setup.workspace import Workspace

PROJECT_NAME_ENV = "COMPOSE_PROJECT_NAME"
COMPOSE_NAME_KEY = "name"
LS_COMMAND = ("docker", "compose", "ls", "-a", "--format", "json")
LS_NAME_KEY = "Name"
LS_CONFIG_FILES_KEY = "ConfigFiles"
CONFIG_FILES_SEPARATOR = ","


@dataclass(frozen=True)
class ProjectOwner:
    name: str
    config_dir: Path | None


class ProjectConflict(RuntimeError):
    """The compose project is already owned by another directory."""


def project_name(workspace: Workspace, environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    override = env.get(PROJECT_NAME_ENV, "").strip()
    if override:
        return override
    compose_name = workspace.compose_name()
    return compose_name or workspace.root.name


def _same_dir(left: Path, right: Path) -> bool:
    return (
        PureWindowsPath(str(left)).as_posix().lower()
        == PureWindowsPath(str(right)).as_posix().lower()
    )


def current_owner(shell: Shell, name: str) -> ProjectOwner | None:
    """The directory whose compose file owns `name`, or None when no such project exists."""
    completed = shell.run(list(LS_COMMAND))
    if completed.returncode != 0:
        return None
    try:
        projects = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(projects, list):
        return None
    for project in projects:
        if project.get(LS_NAME_KEY) != name:
            continue
        files = str(project.get(LS_CONFIG_FILES_KEY, ""))
        first = files.split(CONFIG_FILES_SEPARATOR)[0].strip()
        return ProjectOwner(name, Path(first).parent if first else None)
    return None


def ensure_project_is_ours(shell: Shell, workspace: Workspace) -> str:
    """Return the project name, or raise when another directory already owns it."""
    name = project_name(workspace)
    owner = current_owner(shell, name)
    owned_elsewhere = (
        owner is not None
        and owner.config_dir is not None
        and not _same_dir(owner.config_dir, workspace.root)
    )
    if owned_elsewhere:
        assert owner is not None
        raise ProjectConflict(
            f"compose project '{name}' is already running from {owner.config_dir}; "
            f"stop that stack, or set {PROJECT_NAME_ENV} to run this clone separately"
        )
    return name
