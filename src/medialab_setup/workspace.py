"""The medialab workspace on disk: which `.env` files exist and where state goes.

The service list is read from `docker-compose.yml`, as `bin/lib.sh` does: a
service with a `build:` key is one of ours and keeps its `.env` in its
directory. The root `.env` and `gluetun/vpn.env` are fixed extras.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path

import yaml

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

    def built_services(self) -> list[str]:
        if not self.compose_path.exists():
            raise FileNotFoundError(self.compose_path)
        compose = yaml.safe_load(self.compose_path.read_text(encoding="utf-8")) or {}
        services = compose.get(COMPOSE_SERVICES_KEY, {})
        return [name for name, spec in services.items() if COMPOSE_BUILD_KEY in (spec or {})]

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
