from pathlib import Path

import pytest
from fakes import FakeShell

from medialab_setup.scripts import (
    GIT_BASH,
    ScriptError,
    bash_executable,
    compose_up_command,
    run_or_raise,
    script_command,
)
from medialab_setup.workspace import Workspace


def test_git_bash_preferred_over_path_bash() -> None:
    shell = FakeShell(commands={"bash"}, existing_paths={GIT_BASH})
    assert bash_executable(shell) == str(GIT_BASH)


def test_path_bash_is_the_fallback() -> None:
    shell = FakeShell(commands={"bash"})
    assert bash_executable(shell).endswith("bash.exe")


def test_no_bash_is_an_error() -> None:
    with pytest.raises(ScriptError, match="Git Bash"):
        bash_executable(FakeShell(commands=set()))


def test_script_command_points_into_the_workspace(workspace_root: Path) -> None:
    shell = FakeShell(existing_paths={GIT_BASH})
    command = script_command(shell, Workspace(workspace_root), "bin/x.sh", "--dry-run")
    assert command == [str(GIT_BASH), str(workspace_root / "bin/x.sh"), "--dry-run"]


def test_compose_up_names_both_env_files(workspace_root: Path) -> None:
    command = compose_up_command(Workspace(workspace_root))
    assert command[:2] == ["docker", "compose"]
    assert command.count("--env-file") == 2
    assert command[-2:] == ["up", "-d"]


def test_run_or_raise_reports_exit_code() -> None:
    shell = FakeShell()
    shell.expect_stream("boom", 3)
    with pytest.raises(ScriptError, match="exited 3"):
        run_or_raise(shell, ["boom"], "boom")
