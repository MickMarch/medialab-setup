"""Test doubles for the host boundary and the operator."""

from __future__ import annotations

import subprocess
from collections import deque
from collections.abc import Mapping
from pathlib import Path

from medialab_setup.shell import Shell

GIB = 1024**3


class FakeShell(Shell):
    def __init__(
        self,
        *,
        commands: set[str] | None = None,
        open_ports: set[int] | None = None,
        existing_paths: set[Path] | None = None,
        http: Mapping[str, str | None] | None = None,
        free_bytes: int = 500 * GIB,
    ) -> None:
        self.commands = set(commands or {"git", "uv", "docker", "winget"})
        self.open_ports = set(open_ports or set())
        self.existing_paths = set(existing_paths or set())
        self.http = dict(http or {})
        self.free_bytes = free_bytes
        self.runs: list[list[str]] = []
        self.results: dict[str, subprocess.CompletedProcess[str]] = {}
        self.install_adds: dict[str, str] = {}

    def which(self, name: str) -> str | None:
        return f"C:/bin/{name}.exe" if name in self.commands else None

    def expect(self, prefix: str, returncode: int = 0, stdout: str = "") -> None:
        self.results[prefix] = subprocess.CompletedProcess([prefix], returncode, stdout, "")

    def run(self, args: list[str], *, timeout: float = 0) -> subprocess.CompletedProcess[str]:
        self.runs.append(args)
        joined = " ".join(args)
        if args[:2] == ["winget", "install"]:
            command = self.install_adds.get(args[-1])
            if command:
                self.commands.add(command)
        for prefix, result in self.results.items():
            if joined.startswith(prefix):
                return result
        return subprocess.CompletedProcess(args, 0, "", "")

    def port_open(self, port: int, host: str = "") -> bool:
        return port in self.open_ports

    def disk_free_bytes(self, path: Path) -> int:
        return self.free_bytes

    def http_get_text(self, url: str) -> str | None:
        return self.http.get(url)

    def path_exists(self, path: Path) -> bool:
        return path in self.existing_paths


class ScriptedPrompter:
    """Answers prompts from a queue per message; records notes and questions."""

    def __init__(self, script: dict[str, list[str]] | None = None, confirms: bool = False) -> None:
        self.script = {title: deque(values) for title, values in (script or {}).items()}
        self.confirms = confirms
        self.notes: list[str] = []
        self.asked: list[str] = []
        self.confirmed: list[str] = []

    def _pop(self, message: str) -> str:
        self.asked.append(message)
        queue = self.script.get(message)
        return queue.popleft() if queue else ""

    def text(self, message: str, default: str, help_text: str) -> str:
        return self._pop(message) or default

    def secret(self, message: str, has_current: bool, help_text: str) -> str:
        return self._pop(message)

    def confirm(self, message: str, default: bool) -> bool:
        self.confirmed.append(message)
        return self.confirms

    def note(self, text: str) -> None:
        self.notes.append(text)
