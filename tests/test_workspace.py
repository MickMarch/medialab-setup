from pathlib import Path

import pytest

from medialab_setup.workspace import GLUETUN_TARGET, ROOT_TARGET, Workspace


def test_env_targets_come_from_compose_build_services(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    names = [target.name for target in workspace.env_targets()]
    assert names == [ROOT_TARGET, "svc-a", "svc-b", GLUETUN_TARGET]


def test_env_target_paths(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    by_name = {target.name: target for target in workspace.env_targets()}
    assert by_name[ROOT_TARGET].example_path == workspace_root / ".env.example"
    assert by_name[ROOT_TARGET].env_path == workspace_root / ".env"
    assert by_name["svc-a"].env_path == workspace_root / "svc-a" / ".env"
    assert by_name[GLUETUN_TARGET].env_path == workspace_root / "gluetun" / "vpn.env"


def test_missing_compose_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Workspace(tmp_path).env_targets()


def test_backup_dir_is_under_state_dir(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    assert workspace.backup_dir.parent == workspace_root / ".medialab-setup" / "backup"


def test_published_ports_resolve_interpolation_from_root_env(workspace_root: Path) -> None:
    (workspace_root / "docker-compose.yml").write_text(
        "services:\n"
        "  svc-a:\n    build: {context: ./svc-a}\n    ports: ['127.0.0.1:${A_PORT:-8000}:8000']\n"
        "  svc-b:\n    build: {context: ./svc-b}\n    ports: ['8081:8080']\n"
        "  svc-c:\n    image: x\n"
    )
    assert Workspace(workspace_root).published_ports() == {"svc-a": 8000, "svc-b": 8081}
    (workspace_root / ".env").write_text("A_PORT=9000\n")
    assert Workspace(workspace_root).published_ports()["svc-a"] == 9000
