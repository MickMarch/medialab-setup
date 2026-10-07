"""The update command: check, snapshot, fetch, migrate, apply, verify, roll back on failure."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table

from medialab_setup.bindings import BINDINGS, REQUIRED_FIELDS, Binding
from medialab_setup.collect import CollectError
from medialab_setup.compose_project import ProjectConflict, ensure_project_is_ours
from medialab_setup.envfile import EnvTemplate, parse_env_values
from medialab_setup.generate import collect_existing, render_all, write_all
from medialab_setup.gitops import DEFAULT_TARGET, MAIN, Git
from medialab_setup.prompts import Prompter
from medialab_setup.scripts import (
    BUILD_SCRIPT,
    VERSIONS_FILE,
    compose_up_command,
    run_or_raise,
    script_command,
    wait_for_doctor,
)
from medialab_setup.shell import Shell
from medialab_setup.workspace import Workspace

SNAPSHOT_FILE = "snapshot.json"
SNAPSHOT_ROOT_KEY = "root_commit"
UP_TO_DATE = "up to date"
IMAGE_TAG_SEPARATOR = ":"
COMPOSE_RUNNING_STATE = "running"


class UpdateError(RuntimeError):
    """A precondition failed; nothing was changed."""


class RolledBack(RuntimeError):
    """Verify failed after apply and the previous state was restored."""


@dataclass(frozen=True)
class UpdateOptions:
    to: str | None = None
    dry_run: bool = False
    rollback: bool = True
    interactive: bool = True


@dataclass(frozen=True)
class ServiceRow:
    service: str
    running: str
    pinned: str
    target: str

    @property
    def moves(self) -> bool:
        """The pin will change."""
        return self.pinned != self.target

    @property
    def stale(self) -> bool:
        """The running image is not the pinned version (or nothing is running)."""
        return self.running != self.pinned

    @property
    def needs_work(self) -> bool:
        return self.moves or self.stale


@dataclass
class UpdateContext:
    workspace: Workspace
    options: UpdateOptions
    shell: Shell
    prompter: Prompter
    console: Console
    bindings: tuple[Binding, ...] = BINDINGS
    git: Git = field(init=False)
    snapshot_commit: str | None = None

    def __post_init__(self) -> None:
        self.git = Git(self.shell, self.workspace.root)

    @property
    def target(self) -> str:
        return self.options.to or DEFAULT_TARGET


# Check


def running_versions(ctx: UpdateContext) -> dict[str, str]:
    completed = ctx.shell.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(ctx.workspace.root),
            "ps",
            "--format",
            "json",
        ]
    )
    versions: dict[str, str] = {}
    if completed.returncode != 0:
        return versions
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        image = str(record.get("Image", ""))
        _, _, tag = image.rpartition(IMAGE_TAG_SEPARATOR)
        versions[str(record.get("Service", ""))] = tag
    return versions


def check(ctx: UpdateContext) -> list[ServiceRow]:
    ctx.git.fetch()
    running = running_versions(ctx)
    rows: list[ServiceRow] = []
    for service in ctx.workspace.built_services():
        pinned = ctx.git.describe(service)
        target_sha = ctx.git.submodule_sha_at(ctx.target, service)
        if target_sha is None:
            target = pinned
        else:
            ctx.git.fetch_submodule(service)
            target = ctx.git.describe(service, target_sha)
        rows.append(ServiceRow(service, running.get(service, "-"), pinned, target))
    return rows


def check_table(rows: list[ServiceRow]) -> Table:
    table = Table(title="Services")
    for column in ("Service", "Running", "Pinned", "Target"):
        table.add_column(column)
    for row in rows:
        table.add_row(row.service, row.running, row.pinned, row.target)
    return table


# Snapshot and rollback


def snapshot(ctx: UpdateContext) -> None:
    backup = ctx.workspace.backup_dir
    backup.mkdir(parents=True, exist_ok=True)
    ctx.snapshot_commit = ctx.git.head()
    (backup / SNAPSHOT_FILE).write_text(
        json.dumps({SNAPSHOT_ROOT_KEY: ctx.snapshot_commit}), encoding="utf-8"
    )
    for target in ctx.workspace.env_targets():
        if target.env_path.exists():
            dest = backup / target.env_path.relative_to(ctx.workspace.root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target.env_path, dest)
    versions = ctx.workspace.root / VERSIONS_FILE
    if versions.exists():
        shutil.copy2(versions, backup / VERSIONS_FILE)


def rollback(ctx: UpdateContext) -> None:
    if ctx.snapshot_commit is None:
        raise UpdateError("no snapshot to roll back to")
    ctx.console.rule("rollback")
    ctx.git.checkout_detached(ctx.snapshot_commit)
    ctx.git.submodule_update()
    backup = ctx.workspace.backup_dir
    for target in ctx.workspace.env_targets():
        saved = backup / target.env_path.relative_to(ctx.workspace.root)
        if saved.exists():
            shutil.copy2(saved, target.env_path)
    apply(ctx)
    green = wait_for_doctor(ctx.shell, ctx.workspace, ctx.console.print)
    state = "green" if green else "still failing"
    ctx.console.print(
        f"Rolled back to {ctx.snapshot_commit[:12]} (detached); doctor {state}. "
        f"Return to the branch with: git switch {MAIN}"
    )


# Fetch, migrate, apply, verify


def fetch(ctx: UpdateContext) -> None:
    if ctx.git.branch() != MAIN:
        raise UpdateError(f"root checkout is not on {MAIN}; update only moves {MAIN}")
    if not ctx.git.is_clean():
        raise UpdateError("root checkout has uncommitted changes; commit or stash them first")
    ctx.git.merge_ff(ctx.target)
    ctx.git.submodule_update()


def migrate_config(ctx: UpdateContext) -> Table:
    """Append template keys the live .env files lack; flag keys the template dropped."""
    answers = collect_existing(ctx.workspace, ctx.bindings).with_generated()
    rendered = render_all(ctx.workspace, answers, ctx.bindings)
    table = Table(title="Config migration")
    table.add_column("File")
    table.add_column("Added")
    table.add_column("Removed from template")
    unresolved: list[str] = []
    for target in ctx.workspace.env_targets():
        if target.name not in rendered:
            continue
        template = EnvTemplate.from_path(target.example_path)
        existing = (
            parse_env_values(target.env_path.read_text(encoding="utf-8"))
            if target.env_path.exists()
            else {}
        )
        new_values = parse_env_values(rendered[target.name])
        added = [key for key in template.keys if key not in existing]
        removed = [key for key in existing if key not in template.keys]
        unresolved.extend(
            f"{target.name}:{key}"
            for key in added
            if new_values.get(key, "") == "" and _needs_value(ctx, target.name, key)
        )
        if added or removed:
            table.add_row(target.name, ", ".join(added), ", ".join(removed))
    if unresolved:
        raise CollectError(
            "new settings with no default need a value; run setup --custom first: "
            + ", ".join(unresolved)
        )
    if not ctx.options.dry_run:
        write_all(ctx.workspace, rendered)
    return table


def _needs_value(ctx: UpdateContext, target: str, key: str) -> bool:
    """An empty new key blocks only when nothing can supply it: unbound, or a required answer."""
    for binding in ctx.bindings:
        if binding.target == target and binding.key == key:
            return binding.field in REQUIRED_FIELDS
    return True


def apply(ctx: UpdateContext) -> None:
    build = script_command(ctx.shell, ctx.workspace, BUILD_SCRIPT)
    up = compose_up_command(ctx.workspace)
    ctx.console.print(f"$ {' '.join(build)}")
    ctx.console.print(f"$ {' '.join(up)}")
    if ctx.options.dry_run:
        return
    run_or_raise(ctx.shell, build, BUILD_SCRIPT)
    run_or_raise(ctx.shell, up, "docker compose up")


def run_update(ctx: UpdateContext) -> bool:
    """Returns True when something was updated, False when already up to date."""
    ctx.console.rule("check")
    try:
        ensure_project_is_ours(ctx.shell, ctx.workspace)
    except ProjectConflict as conflict:
        raise UpdateError(str(conflict)) from conflict
    rows = check(ctx)
    ctx.console.print(check_table(rows))
    commits = ctx.git.commits_between("HEAD", ctx.target)
    for commit in commits:
        ctx.console.print(f"  {commit.sha} {commit.subject}")
    if not commits and not any(row.needs_work for row in rows):
        ctx.console.print(UP_TO_DATE)
        return False
    stale = [row.service for row in rows if row.stale and not row.moves]
    if stale:
        ctx.console.print(f"Running behind the pin, will rebuild: {', '.join(stale)}")
    if ctx.options.dry_run:
        ctx.console.print("Dry run: would snapshot, fetch, migrate, build, recreate and verify.")
        return True
    ctx.console.rule("snapshot")
    snapshot(ctx)
    ctx.console.print(f"Snapshot at {ctx.workspace.backup_dir}")
    ctx.console.rule("fetch")
    fetch(ctx)
    ctx.console.rule("migrate")
    ctx.console.print(migrate_config(ctx))
    ctx.console.rule("apply")
    apply(ctx)
    ctx.console.rule("verify")
    if wait_for_doctor(ctx.shell, ctx.workspace, ctx.console.print):
        return True
    if not ctx.options.rollback:
        raise UpdateError("doctor failed after update; --no-rollback left the new state in place")
    rollback(ctx)
    raise RolledBack("doctor failed after update; previous state restored")
