"""The host boundary: processes, ports, disk, local HTTP. Faked in tests."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx

COMMAND_TIMEOUT_SECONDS = 600
PORT_PROBE_TIMEOUT_SECONDS = 0.5
HTTP_TIMEOUT_SECONDS = 5.0
LOOPBACK = "127.0.0.1"


class Shell:
    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def run(
        self, args: list[str], *, timeout: float = COMMAND_TIMEOUT_SECONDS
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)

    def stream(self, args: list[str], *, timeout: float = COMMAND_TIMEOUT_SECONDS) -> int:
        """Run with output going straight to the terminal; returns the exit code."""
        return subprocess.run(args, timeout=timeout, check=False).returncode

    def run_elevated(self, script_path: Path) -> int:
        """Run a PowerShell script through UAC and wait; returns the launcher's exit code."""
        launcher = (
            f"Start-Process powershell -Verb RunAs -Wait -ArgumentList "
            f"'-NoProfile -ExecutionPolicy Bypass -File \"{script_path}\"'"
        )
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", launcher],
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        ).returncode

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def port_open(self, port: int, host: str = LOOPBACK) -> bool:
        try:
            with socket.create_connection((host, port), timeout=PORT_PROBE_TIMEOUT_SECONDS):
                return True
        except OSError:
            return False

    def disk_free_bytes(self, path: Path) -> int:
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return shutil.disk_usage(probe).free

    def http_get_text(self, url: str) -> str | None:
        try:
            response = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        except httpx.TransportError:
            return None
        return response.text if response.is_success else None

    def path_exists(self, path: Path) -> bool:
        return path.exists()
