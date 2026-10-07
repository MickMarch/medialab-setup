"""Phase Preflight: is the host ready, and install what winget can when it is not."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from medialab_setup.compose_project import ProjectConflict, ensure_project_is_ours
from medialab_setup.prompts import Prompter, UrlOpener, open_in_browser
from medialab_setup.shell import Shell
from medialab_setup.workspace import Workspace

JELLYFIN_HEALTH_URL = "http://127.0.0.1:8096/health"
JELLYFIN_HEALTHY = "Healthy"
JELLYFIN_EXE = Path(r"C:\Program Files\Jellyfin\Server\jellyfin.exe")
HOST_QBITTORRENT_PROCESS = "qbittorrent.exe"
SUBMODULE_UNINITIALISED_PREFIX = "-"
COMPOSE_RUNNING_STATE = "running"
WINGET = "winget"
WINGET_INSTALL_ARGS = (
    "install",
    "--exact",
    "--silent",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--id",
)


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Row:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True)
class Prerequisite:
    name: str
    command: str | None
    winget_id: str
    download_url: str
    after_install: str = ""


PREREQUISITES: tuple[Prerequisite, ...] = (
    Prerequisite("Git", "git", "Git.Git", "https://git-scm.com/download/win"),
    Prerequisite(
        "uv", "uv", "astral-sh.uv", "https://docs.astral.sh/uv/getting-started/installation/"
    ),
    Prerequisite(
        "Docker Desktop",
        "docker",
        "Docker.DockerDesktop",
        "https://www.docker.com/products/docker-desktop/",
        after_install="sign out and back in, start Docker Desktop, then run setup again",
    ),
    Prerequisite(
        "Jellyfin Server",
        None,
        "Jellyfin.Server",
        "https://jellyfin.org/downloads/server",
        after_install="finish the Jellyfin first-run wizard in the browser, then run setup again",
    ),
)


class PreflightError(RuntimeError):
    """A failing row that setup cannot proceed past."""


@dataclass
class PreflightResult:
    rows: list[Row] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(row.status is Status.FAIL for row in self.rows)


class Preflight:
    def __init__(
        self,
        workspace: Workspace,
        shell: Shell,
        prompter: Prompter,
        *,
        assume_yes: bool = False,
        interactive: bool = True,
        opener: UrlOpener = open_in_browser,
    ) -> None:
        self.workspace = workspace
        self.shell = shell
        self.prompter = prompter
        self.assume_yes = assume_yes
        self.interactive = interactive
        self.opener = opener

    def run(self) -> PreflightResult:
        result = PreflightResult()
        for prerequisite in PREREQUISITES:
            result.rows.append(self._prerequisite_row(prerequisite))
        result.rows.append(self._submodules_row())
        result.rows.append(self._docker_engine_row())
        result.rows.append(self._compose_project_row())
        result.rows.extend(self._port_rows())
        result.rows.append(self._host_qbittorrent_row())
        return result

    # Prerequisites

    def _installed(self, prerequisite: Prerequisite) -> bool:
        if prerequisite.command is not None:
            return self.shell.which(prerequisite.command) is not None
        return self.shell.path_exists(JELLYFIN_EXE) or self._jellyfin_healthy()

    def _jellyfin_healthy(self) -> bool:
        body = self.shell.http_get_text(JELLYFIN_HEALTH_URL)
        return body is not None and JELLYFIN_HEALTHY in body

    def _prerequisite_row(self, prerequisite: Prerequisite) -> Row:
        if self._installed(prerequisite):
            return Row(Status.OK, prerequisite.name, "installed")
        if not self._confirm(f"{prerequisite.name} is missing. Install it now?"):
            return Row(
                Status.FAIL, prerequisite.name, f"missing; install from {prerequisite.download_url}"
            )
        installed_via = self._install(prerequisite)
        if not self._installed(prerequisite):
            return Row(
                Status.FAIL,
                prerequisite.name,
                f"still missing after {installed_via}; {prerequisite.after_install or 'retry'}",
            )
        detail = f"installed via {installed_via}"
        if prerequisite.after_install:
            detail = f"{detail}; {prerequisite.after_install}"
        return Row(Status.OK, prerequisite.name, detail)

    def _install(self, prerequisite: Prerequisite) -> str:
        if self.shell.which(WINGET) is not None:
            command = [WINGET, *WINGET_INSTALL_ARGS, prerequisite.winget_id]
            self.prompter.note(f"$ {' '.join(command)}")
            completed = self.shell.run(command)
            if completed.returncode == 0:
                return WINGET
            self.prompter.note(
                f"{WINGET} failed (exit {completed.returncode}); opening the download page"
            )
        self.opener(prerequisite.download_url)
        self._confirm(f"Finished installing {prerequisite.name} from {prerequisite.download_url}?")
        return "download page"

    def _confirm(self, message: str) -> bool:
        if self.assume_yes:
            return True
        if not self.interactive:
            return False
        return self.prompter.confirm(message, default=True)

    # Workspace and engine

    def _submodules_row(self) -> Row:
        completed = self.shell.run(["git", "-C", str(self.workspace.root), "submodule", "status"])
        if completed.returncode != 0:
            return Row(Status.FAIL, "submodules", "git submodule status failed; is this a clone?")
        missing = [
            line.split()[1]
            for line in completed.stdout.splitlines()
            if line.startswith(SUBMODULE_UNINITIALISED_PREFIX)
        ]
        if missing:
            return Row(
                Status.FAIL,
                "submodules",
                f"not initialised: {', '.join(missing)}; run git submodule update --init",
            )
        return Row(Status.OK, "submodules", "all initialised")

    def _docker_engine_row(self) -> Row:
        if self.shell.which("docker") is None:
            return Row(Status.FAIL, "docker engine", "docker command not found")
        completed = self.shell.run(["docker", "info", "--format", "{{.ServerVersion}}"])
        if completed.returncode != 0:
            return Row(Status.FAIL, "docker engine", "not reachable; start Docker Desktop")
        return Row(Status.OK, "docker engine", completed.stdout.strip())

    def _compose_project_row(self) -> Row:
        try:
            name = ensure_project_is_ours(self.shell, self.workspace)
        except ProjectConflict as conflict:
            return Row(Status.FAIL, "compose project", str(conflict))
        return Row(Status.OK, "compose project", f"'{name}' is free or ours")

    def _running_services(self) -> set[str]:
        completed = self.shell.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(self.workspace.root),
                "ps",
                "--format",
                "json",
            ]
        )
        if completed.returncode != 0:
            return set()
        running: set[str] = set()
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("State") == COMPOSE_RUNNING_STATE:
                running.add(str(record.get("Service", "")))
        return running

    def _port_rows(self) -> list[Row]:
        rows: list[Row] = []
        running = self._running_services()
        for service, port in self.workspace.published_ports().items():
            name = f"port {port}"
            if not self.shell.port_open(port):
                rows.append(Row(Status.OK, name, f"free for {service}"))
            elif service in running:
                rows.append(Row(Status.OK, name, f"held by our {service} container"))
            else:
                rows.append(
                    Row(
                        Status.WARN,
                        name,
                        f"held by another process; {service} will fail to publish",
                    )
                )
        return rows

    def _host_qbittorrent_row(self) -> Row:
        completed = self.shell.run(["tasklist"])
        if completed.returncode == 0 and HOST_QBITTORRENT_PROCESS in completed.stdout.lower():
            return Row(
                Status.WARN,
                "host qBittorrent",
                "running on the host; disable its autostart so two clients never share "
                "the staging folders",
            )
        return Row(Status.OK, "host qBittorrent", "not running")
