"""The medialab workspace on disk: which `.env` files exist and where state goes.

The service list is read from `docker-compose.yml`, as `bin/lib.sh` does: a
service with a `build:` key is one of ours and keeps its `.env` in its
directory. The root `.env` and `gluetun/vpn.env` are fixed extras.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from medialab_setup.envfile import parse_env_values

COMPOSE_FILE = "docker-compose.yml"
ENV_FILE = ".env"
ENV_EXAMPLE_FILE = ".env.example"
ROOT_TARGET = "root"
GLUETUN_TARGET = "gluetun"
GLUETUN_DIR = "gluetun"
GLUETUN_ENV_FILE = "vpn.env"
GLUETUN_ENV_EXAMPLE_FILE = "vpn.env.example"
STATE_DIR = ".medialab-setup"
BACKUP_DIR = "backup"
BACKUP_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
COMPOSE_SERVICES_KEY = "services"
COMPOSE_BUILD_KEY = "build"
COMPOSE_PORTS_KEY = "ports"
PORT_SEPARATOR = ":"
# "host:container" has two parts; "ip:host:container" has three.
PORT_PARTS_WITH_HOST = 2
# "${VAR:-default}" or "${VAR}" inside a compose string.
INTERPOLATION_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>[^}]*))?\}")


@dataclass(frozen=True)
class EnvTarget:
    name: str
    example_path: Path
    env_path: Path


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def compose_path(self) -> Path:
        return self.root / COMPOSE_FILE

    @cached_property
    def backup_dir(self) -> Path:
        stamp = datetime.now(UTC).strftime(BACKUP_TIMESTAMP_FORMAT)
        return self.root / STATE_DIR / BACKUP_DIR / stamp

    def _services(self) -> dict[str, dict[str, Any]]:
        if not self.compose_path.exists():
            raise FileNotFoundError(self.compose_path)
        compose = yaml.safe_load(self.compose_path.read_text(encoding="utf-8")) or {}
        services = compose.get(COMPOSE_SERVICES_KEY, {})
        return {name: (spec or {}) for name, spec in services.items()}

    def built_services(self) -> list[str]:
        return [name for name, spec in self._services().items() if COMPOSE_BUILD_KEY in spec]

    def root_env_values(self) -> dict[str, str]:
        path = self.root / ENV_FILE
        if not path.exists():
            return {}
        return parse_env_values(path.read_text(encoding="utf-8"))

    def published_ports(self) -> dict[str, int]:
        """Host port per service, with compose interpolation resolved from the root .env."""
        env = self.root_env_values()

        def expand(match: re.Match[str]) -> str:
            return env.get(match["name"]) or (match["default"] or "")

        ports: dict[str, int] = {}
        for name, spec in self._services().items():
            for entry in spec.get(COMPOSE_PORTS_KEY, []) or []:
                text = INTERPOLATION_PATTERN.sub(expand, str(entry))
                parts = text.split(PORT_SEPARATOR)
                host_port = parts[-2] if len(parts) >= PORT_PARTS_WITH_HOST else parts[0]
                if host_port.isdigit():
                    ports[name] = int(host_port)
        return ports

    def env_targets(self) -> list[EnvTarget]:
        targets = [EnvTarget(ROOT_TARGET, self.root / ENV_EXAMPLE_FILE, self.root / ENV_FILE)]
        targets.extend(
            EnvTarget(
                service,
                self.root / service / ENV_EXAMPLE_FILE,
                self.root / service / ENV_FILE,
            )
            for service in self.built_services()
        )
        gluetun = self.root / GLUETUN_DIR
        targets.append(
            EnvTarget(
                GLUETUN_TARGET,
                gluetun / GLUETUN_ENV_EXAMPLE_FILE,
                gluetun / GLUETUN_ENV_FILE,
            )
        )
        return targets
