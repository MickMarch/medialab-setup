import json
from pathlib import Path

import pytest
from fakes import FakeShell

from medialab_setup.compose_project import (
    PROJECT_NAME_ENV,
    ProjectConflict,
    current_owner,
    ensure_project_is_ours,
    project_name,
)
from medialab_setup.workspace import Workspace


def _ls(name: str, config_dir: Path) -> str:
    return json.dumps(
        [
            {
                "Name": name,
                "Status": "running(2)",
                "ConfigFiles": str(config_dir / "docker-compose.yml"),
            }
        ]
    )


def test_project_name_prefers_env_then_file_then_directory(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    assert project_name(workspace, {}) == workspace_root.name
    (workspace_root / "docker-compose.yml").write_text(
        "name: medialab\nservices:\n  svc-a:\n    build: {context: ./svc-a}\n"
    )
    assert project_name(workspace, {}) == "medialab"
    assert project_name(workspace, {PROJECT_NAME_ENV: "scratch"}) == "scratch"


def test_no_project_means_no_owner(workspace_root: Path) -> None:
    shell = FakeShell()
    assert current_owner(shell, "medialab") is None
    assert ensure_project_is_ours(shell, Workspace(workspace_root)) == workspace_root.name


def test_own_directory_is_not_a_conflict(workspace_root: Path) -> None:
    shell = FakeShell()
    shell.compose_ls_json = _ls(workspace_root.name, workspace_root)
    assert ensure_project_is_ours(shell, Workspace(workspace_root)) == workspace_root.name


def test_other_directory_is_a_conflict(workspace_root: Path, tmp_path: Path) -> None:
    other = tmp_path / "live"
    shell = FakeShell()
    shell.compose_ls_json = _ls(workspace_root.name, other)
    with pytest.raises(ProjectConflict, match=PROJECT_NAME_ENV):
        ensure_project_is_ours(shell, Workspace(workspace_root))


def test_env_override_sidesteps_the_conflict(
    workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = FakeShell()
    shell.compose_ls_json = _ls(workspace_root.name, tmp_path / "live")
    monkeypatch.setenv(PROJECT_NAME_ENV, "scratch")
    assert ensure_project_is_ours(shell, Workspace(workspace_root)) == "scratch"


def test_unreadable_ls_is_not_a_conflict(workspace_root: Path) -> None:
    shell = FakeShell()
    shell.compose_ls_json = "not json"
    assert ensure_project_is_ours(shell, Workspace(workspace_root)) == workspace_root.name
