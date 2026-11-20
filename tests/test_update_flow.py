from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import FakeShell, ScriptedPrompter
from rich.console import Console

from medialab_setup.bindings import JELLYFIN_WORKER, ORCHESTRATOR, Binding
from medialab_setup.checks import jellyfin_auth_headers
from medialab_setup.collect import CollectError
from medialab_setup.envfile import NOT_IN_TEMPLATE_COMMENT, parse_env_values
from medialab_setup.jellyfin_client import JellyfinClient, Library
from medialab_setup.scripts import DOCTOR_SCRIPT, VERIFY_INTERVAL_SECONDS
from medialab_setup.update_flow import (
    REMOVED_KEYS,
    SNAPSHOT_FILE,
    UP_TO_DATE,
    RolledBack,
    UpdateContext,
    UpdateError,
    UpdateOptions,
    run_update,
)
from medialab_setup.workspace import GLUETUN_TARGET, ROOT_TARGET, Workspace

DOCTOR = Path(DOCTOR_SCRIPT).name
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
ROOT_SHA = "c" * 40
FIXTURE_BINDINGS = (
    Binding(ROOT_TARGET, "MEDIA_HOST_DIR", "media_host_dir"),
    Binding("svc-a", "API_KEY", "downloader_api_key"),
    Binding("svc-b", "SVC_A_API_KEY", "downloader_api_key"),
    Binding("svc-b", "API_KEY", "orchestrator_api_key"),
    Binding(GLUETUN_TARGET, "WIREGUARD_PRIVATE_KEY", "wireguard_private_key"),
)


JELLYFIN_KEY_BINDING = Binding("svc-a", "JELLYFIN_API_KEY", "jellyfin_api_key")


class FakeJellyfin(JellyfinClient):
    instances: list[FakeJellyfin] = []
    existing: list[Library] = []

    def __init__(self, api_key: str, base_url: str = "") -> None:
        super().__init__(api_key, base_url or "http://127.0.0.1:8096")
        self.deleted: list[str] = []
        FakeJellyfin.instances.append(self)

    def list_libraries(self) -> list[Library]:
        return [library for library in FakeJellyfin.existing if library.name not in self.deleted]

    def delete_library(self, name: str) -> None:
        self.deleted.append(name)


@pytest.fixture(autouse=True)
def _reset_fake_jellyfin() -> Iterator[None]:
    FakeJellyfin.instances.clear()
    FakeJellyfin.existing = []
    yield
    FakeJellyfin.existing = []


def _shell(
    *, moved: bool = True, clean: bool = True, branch: str = "main", running: str = "1.2.0"
) -> FakeShell:
    shell = FakeShell()
    shell.expect("rev-parse --abbrev-ref HEAD", stdout=f"{branch}\n")
    shell.expect("rev-parse HEAD", stdout=f"{ROOT_SHA}\n")
    shell.expect("status --porcelain", stdout="" if clean else " M svc-a\n")
    shell.expect("log --oneline", stdout="abc1234 chore: bump svc-a pin\n" if moved else "")
    shell.expect(
        "ls-tree origin/main -- svc-a",
        stdout=f"160000 commit {NEW_SHA if moved else OLD_SHA}\tsvc-a\n",
    )
    shell.expect("ls-tree origin/main -- svc-b", stdout=f"160000 commit {OLD_SHA}\tsvc-b\n")
    shell.expect(f"describe --tags --always {NEW_SHA}", stdout="v1.3.0\n")
    shell.expect(f"describe --tags --always {OLD_SHA}", stdout="v1.2.0\n")
    shell.expect("describe --tags --always", stdout="v1.2.0\n")
    shell.expect(
        "docker compose",
        stdout=(
            f'{{"Service": "svc-a", "Image": "medialab/svc-a:{running}", "State": "running"}}\n'
            f'{{"Service": "svc-b", "Image": "medialab/svc-b:{running}", "State": "running"}}\n'
        ),
    )
    return shell


def _ctx(root: Path, shell: FakeShell, **options: object) -> UpdateContext:
    for svc in ("svc-a", "svc-b"):
        (root / svc / ".env").write_text("API_KEY=k\nSHARED_KEY=s\n")
    (root / ".env").write_text("MEDIA_HOST_DIR=F:/Media\nTZ=UTC\n")
    (root / ".versions.env").write_text("SVC_A_VERSION=1.2.0\n")
    (root / "gluetun" / "vpn.env").write_text("WIREGUARD_PRIVATE_KEY=w\n")
    return UpdateContext(
        workspace=Workspace(root),
        options=UpdateOptions(**options),  # type: ignore[arg-type]
        shell=shell,
        prompter=ScriptedPrompter(),
        console=Console(record=True, width=400),
        bindings=FIXTURE_BINDINGS,
        make_jellyfin_client=FakeJellyfin,
    )


def _streamed(ctx: UpdateContext) -> list[str]:
    return [" ".join(c) for c in ctx.shell.streams]  # type: ignore[attr-defined]


def _git_calls(ctx: UpdateContext) -> list[str]:
    return [" ".join(c[3:]) for c in ctx.shell.runs if c[:1] == ["git"]]  # type: ignore[attr-defined]


def test_up_to_date_exits_early(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(moved=False))
    assert run_update(ctx) is False
    assert UP_TO_DATE in ctx.console.export_text()
    assert _streamed(ctx) == []
    assert not (workspace_root / ".medialab-setup").exists()


def test_check_table_shows_running_pinned_target(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(), dry_run=True)
    run_update(ctx)
    text = ctx.console.export_text()
    assert "svc-a" in text and "1.3.0" in text and "1.2.0" in text
    assert "chore: bump svc-a pin" in text
    assert _streamed(ctx) == []
    assert "merge --ff-only" not in " ".join(_git_calls(ctx))


def test_full_update_snapshots_fetches_migrates_applies_verifies(workspace_root: Path) -> None:
    shell = _shell()
    ctx = _ctx(workspace_root, shell)
    assert run_update(ctx) is True
    git = _git_calls(ctx)
    assert "merge --ff-only origin/main" in git
    assert "submodule update --init --recursive --quiet" in git
    streamed = _streamed(ctx)
    assert any("medialab-build.sh" in c for c in streamed)
    assert any(c.endswith("up -d") for c in streamed)
    assert any(DOCTOR in c for c in streamed)
    backups = list((workspace_root / ".medialab-setup" / "backup").iterdir())
    assert len(backups) == 1
    assert json.loads((backups[0] / SNAPSHOT_FILE).read_text())["root_commit"] == ROOT_SHA
    assert (backups[0] / "svc-a" / ".env").read_text() == "API_KEY=k\nSHARED_KEY=s\n"
    assert (backups[0] / ".versions.env").exists()


def test_migration_appends_new_keys_and_flags_removed(workspace_root: Path) -> None:
    (workspace_root / "svc-a" / ".env.example").write_text(
        "API_KEY=\nSHARED_KEY=\nTUNABLE=10\nNEW_KEY=7\n"
    )
    ctx = _ctx(workspace_root, _shell())
    (workspace_root / "svc-a" / ".env").write_text("API_KEY=k\nSHARED_KEY=s\nLEGACY=1\n")
    run_update(ctx)
    text = (workspace_root / "svc-a" / ".env").read_text()
    values = parse_env_values(text)
    assert values["NEW_KEY"] == "7" and values["TUNABLE"] == "10"
    assert values["API_KEY"] == "k"
    assert NOT_IN_TEMPLATE_COMMENT in text and values["LEGACY"] == "1"
    report = ctx.console.export_text()
    assert "NEW_KEY" in report and "LEGACY" in report


def test_new_secret_without_default_blocks_migration(workspace_root: Path) -> None:
    (workspace_root / "svc-a" / ".env.example").write_text("API_KEY=\nSHARED_KEY=\nNEW_SECRET=\n")
    ctx = _ctx(workspace_root, _shell())
    with pytest.raises(CollectError, match="NEW_SECRET"):
        run_update(ctx)
    assert not any("medialab-build.sh" in c for c in _streamed(ctx))


def test_dirty_root_refuses_before_changing_anything(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(clean=False))
    with pytest.raises(UpdateError, match="uncommitted"):
        run_update(ctx)
    assert "merge --ff-only origin/main" not in _git_calls(ctx)
    assert _streamed(ctx) == []


def test_non_main_branch_refuses(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(branch="feature"))
    with pytest.raises(UpdateError, match="main"):
        run_update(ctx)


def test_failed_verify_rolls_back_to_snapshot(workspace_root: Path) -> None:
    shell = _shell()
    shell.expect_stream(DOCTOR, 1)
    ctx = _ctx(workspace_root, shell)
    with pytest.raises(RolledBack):
        run_update(ctx)
    git = _git_calls(ctx)
    assert f"checkout --quiet --detach {ROOT_SHA}" in git
    assert git.count("submodule update --init --recursive --quiet") == 2
    assert (workspace_root / "svc-a" / ".env").read_text() == "API_KEY=k\nSHARED_KEY=s\n"
    assert sum(1 for c in _streamed(ctx) if "medialab-build.sh" in c) == 2
    assert "git switch main" in ctx.console.export_text()
    assert shell.slept and shell.slept[0] == VERIFY_INTERVAL_SECONDS


def test_no_rollback_leaves_new_state(workspace_root: Path) -> None:
    shell = _shell()
    shell.expect_stream(DOCTOR, 1)
    ctx = _ctx(workspace_root, shell, rollback=False)
    with pytest.raises(UpdateError, match="no-rollback"):
        run_update(ctx)
    assert "checkout --quiet --detach" not in " ".join(_git_calls(ctx))


def test_to_ref_is_used_as_target(workspace_root: Path) -> None:
    shell = _shell()
    shell.expect("ls-tree v9 -- svc-a", stdout=f"160000 commit {NEW_SHA}\tsvc-a\n")
    shell.expect("ls-tree v9 -- svc-b", stdout=f"160000 commit {OLD_SHA}\tsvc-b\n")
    ctx = _ctx(workspace_root, shell, to="v9")
    run_update(ctx)
    assert "merge --ff-only v9" in _git_calls(ctx)


def test_update_refuses_when_project_owned_elsewhere(workspace_root: Path, tmp_path: Path) -> None:
    shell = _shell()
    shell.compose_ls_json = json.dumps(
        [
            {
                "Name": workspace_root.name,
                "ConfigFiles": str(tmp_path / "live" / "docker-compose.yml"),
            }
        ]
    )
    ctx = _ctx(workspace_root, shell)
    with pytest.raises(UpdateError, match="already running from"):
        run_update(ctx)
    assert _git_calls(ctx) == []


def test_running_behind_the_pin_is_work_even_with_no_new_commits(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(moved=False, running="1.1.0"))
    assert run_update(ctx) is True
    assert "Running behind the pin" in ctx.console.export_text()
    assert any("medialab-build.sh" in c for c in _streamed(ctx))


def test_optional_bound_key_with_empty_default_does_not_block_migration(
    workspace_root: Path,
) -> None:
    (workspace_root / "svc-a" / ".env.example").write_text("API_KEY=\nSHARED_KEY=\nWEBHOOK=\n")
    bindings = (*FIXTURE_BINDINGS, Binding("svc-a", "WEBHOOK", "discord_notify_webhook_url"))
    ctx = _ctx(workspace_root, _shell())
    ctx.bindings = bindings
    assert run_update(ctx) is True
    assert parse_env_values((workspace_root / "svc-a" / ".env").read_text())["WEBHOOK"] == ""


def _with_jellyfin_key(ctx: UpdateContext, root: Path) -> None:
    (root / "svc-a" / ".env").write_text("API_KEY=k\nSHARED_KEY=s\nJELLYFIN_API_KEY=j\n")
    ctx.bindings = (*FIXTURE_BINDINGS, JELLYFIN_KEY_BINDING)


def test_update_removes_discover_libraries_under_the_folder_from_root_env(
    workspace_root: Path,
) -> None:
    FakeJellyfin.existing = [
        Library("Discover Movies", "movies", (r"G:\Old\Movies",)),
        Library("Discover Shows", "tvshows", (r"F:\MedialabDiscover\Shows",)),
    ]
    ctx = _ctx(workspace_root, _shell())
    _with_jellyfin_key(ctx, workspace_root)
    (workspace_root / ".env").write_text("MEDIA_HOST_DIR=F:/Media\nDISCOVER_HOST_DIR=G:/Old\n")
    assert run_update(ctx) is True
    assert FakeJellyfin.instances[0].headers == jellyfin_auth_headers("j")
    assert FakeJellyfin.instances[0].deleted == ["Discover Movies"]
    assert "Discover Shows" in ctx.console.export_text()


def test_update_falls_back_to_the_old_default_folder(workspace_root: Path) -> None:
    FakeJellyfin.existing = [
        Library("Discover Movies", "movies", (r"F:\MedialabDiscover\Movies",)),
        Library("Discover Shows", "tvshows", (r"F:\MedialabDiscover\Shows",)),
    ]
    ctx = _ctx(workspace_root, _shell())
    _with_jellyfin_key(ctx, workspace_root)
    run_update(ctx)
    assert FakeJellyfin.instances[0].deleted == ["Discover Movies", "Discover Shows"]


def test_update_without_a_jellyfin_key_skips_the_teardown(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell())
    assert run_update(ctx) is True
    assert FakeJellyfin.instances == []


def test_update_does_not_tear_down_after_a_rollback(workspace_root: Path) -> None:
    shell = _shell()
    shell.expect_stream(DOCTOR, 1)
    ctx = _ctx(workspace_root, shell)
    _with_jellyfin_key(ctx, workspace_root)
    with pytest.raises(RolledBack):
        run_update(ctx)
    assert FakeJellyfin.instances == []


def test_up_to_date_still_retries_the_teardown(workspace_root: Path) -> None:
    FakeJellyfin.existing = [
        Library("Discover Movies", "movies", (r"F:\MedialabDiscover\Movies",)),
    ]
    ctx = _ctx(workspace_root, _shell(moved=False))
    _with_jellyfin_key(ctx, workspace_root)
    assert run_update(ctx) is False
    assert FakeJellyfin.instances[0].deleted == ["Discover Movies"]


def test_dry_run_up_to_date_contacts_no_jellyfin(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(moved=False), dry_run=True)
    _with_jellyfin_key(ctx, workspace_root)
    run_update(ctx)
    assert FakeJellyfin.instances == []


def test_migration_drops_retired_keys_from_their_service_only(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell())
    ctx.removed_keys = {"svc-a": frozenset({"OLD_KEY"})}
    (workspace_root / "svc-a" / ".env").write_text("API_KEY=k\nSHARED_KEY=s\nOLD_KEY=1\n")
    (workspace_root / "svc-b" / ".env").write_text("API_KEY=k\nSHARED_KEY=s\nOLD_KEY=2\n")
    (workspace_root / ".env").write_text("MEDIA_HOST_DIR=F:/Media\nDISCOVER_HOST_DIR=G:/Old\n")
    run_update(ctx)
    assert "OLD_KEY" not in parse_env_values((workspace_root / "svc-a" / ".env").read_text())
    assert parse_env_values((workspace_root / "svc-b" / ".env").read_text())["OLD_KEY"] == "2"
    root_values = parse_env_values((workspace_root / ".env").read_text())
    assert root_values["DISCOVER_HOST_DIR"] == "G:/Old"


def test_retired_discover_keys_are_scoped_to_their_services() -> None:
    expected = {
        JELLYFIN_WORKER: frozenset({"DISCOVER_MOUNT_PATH"}),
        ORCHESTRATOR: frozenset(
            {
                "DISCOVER_REFRESH_SECONDS",
                "DISCOVER_POLL_SECONDS",
                "DISCOVER_RECOMMENDATIONS_PER_TITLE",
                "JELLYFIN_REQUEST_USERS",
                "JELLYFIN_REQUEST_RETRY_HOURS",
                "JELLYFIN_REQUEST_RESOLUTION",
                "JELLYFIN_WEBHOOK_SECRET",
            }
        ),
    }
    assert expected == REMOVED_KEYS
    assert ROOT_TARGET not in REMOVED_KEYS


def test_dry_run_update_contacts_no_jellyfin(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root, _shell(), dry_run=True)
    _with_jellyfin_key(ctx, workspace_root)
    run_update(ctx)
    assert FakeJellyfin.instances == []
