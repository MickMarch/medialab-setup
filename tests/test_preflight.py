from pathlib import Path

from fakes import FakeShell, ScriptedPrompter

from medialab_setup.preflight import (
    JELLYFIN_EXE,
    JELLYFIN_HEALTH_URL,
    Preflight,
    PreflightResult,
    Status,
)
from medialab_setup.workspace import Workspace

HEALTHY = {JELLYFIN_HEALTH_URL: "Healthy"}


def _rows(result: PreflightResult) -> dict[str, tuple[Status, str]]:
    return {row.name: (row.status, row.detail) for row in result.rows}


def _ready_shell() -> FakeShell:
    shell = FakeShell(http=HEALTHY)
    shell.expect("git -C", stdout=" abc svc-a (v1)\n abc svc-b (v1)\n")
    shell.expect("docker info", stdout="28.0.0\n")
    shell.expect("docker compose", stdout="")
    shell.expect("tasklist", stdout="explorer.exe\n")
    return shell


def test_ready_host_is_all_ok(workspace_root: Path) -> None:
    result = Preflight(Workspace(workspace_root), _ready_shell(), ScriptedPrompter()).run()
    assert not result.failed
    assert {row.status for row in result.rows} == {Status.OK}


def test_missing_prerequisite_installs_via_winget_on_confirm(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.commands.discard("uv")
    shell.install_adds["astral-sh.uv"] = "uv"
    prompter = ScriptedPrompter(confirms=True)
    result = Preflight(Workspace(workspace_root), shell, prompter).run()
    rows = _rows(result)
    assert rows["uv"][0] is Status.OK
    assert "winget" in rows["uv"][1]
    assert any(run[:2] == ["winget", "install"] and "astral-sh.uv" in run for run in shell.runs)
    assert any("--accept-package-agreements" in run for run in shell.runs)


def test_declined_install_is_a_failure_with_the_download_url(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.commands.discard("git")
    result = Preflight(Workspace(workspace_root), shell, ScriptedPrompter(confirms=False)).run()
    status, detail = _rows(result)["Git"]
    assert status is Status.FAIL
    assert "git-scm.com" in detail
    assert result.failed


def test_no_winget_opens_download_page_and_waits(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.commands -= {"winget", "uv"}
    opened: list[str] = []
    prompter = ScriptedPrompter(confirms=True)
    result = Preflight(Workspace(workspace_root), shell, prompter, opener=opened.append).run()
    assert any("astral.sh" in url for url in opened)
    assert any("Finished installing uv" in message for message in prompter.confirmed)
    assert _rows(result)["uv"][0] is Status.FAIL


def test_assume_yes_installs_without_asking(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.commands.discard("uv")
    shell.install_adds["astral-sh.uv"] = "uv"
    prompter = ScriptedPrompter(confirms=False)
    result = Preflight(Workspace(workspace_root), shell, prompter, assume_yes=True).run()
    assert _rows(result)["uv"][0] is Status.OK
    assert prompter.confirmed == []


def test_non_interactive_never_installs(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.commands.discard("uv")
    result = Preflight(
        Workspace(workspace_root), shell, ScriptedPrompter(confirms=True), interactive=False
    ).run()
    assert _rows(result)["uv"][0] is Status.FAIL
    assert not any(run[:1] == ["winget"] for run in shell.runs)


def test_jellyfin_counts_as_installed_when_exe_exists_but_not_running(
    workspace_root: Path,
) -> None:
    shell = _ready_shell()
    shell.http = {}
    shell.existing_paths.add(JELLYFIN_EXE)
    result = Preflight(Workspace(workspace_root), shell, ScriptedPrompter()).run()
    assert _rows(result)["Jellyfin Server"][0] is Status.OK


def test_docker_present_but_engine_down_fails(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.expect("docker info", returncode=1)
    result = Preflight(Workspace(workspace_root), shell, ScriptedPrompter()).run()
    status, detail = _rows(result)["docker engine"]
    assert status is Status.FAIL
    assert "Docker Desktop" in detail


def test_uninitialised_submodule_fails(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.expect("git -C", stdout="-abc svc-b\n abc svc-a (v1)\n")
    result = Preflight(Workspace(workspace_root), shell, ScriptedPrompter()).run()
    status, detail = _rows(result)["submodules"]
    assert status is Status.FAIL
    assert "svc-b" in detail


def test_port_held_by_foreign_process_warns_but_ours_is_ok(workspace_root: Path) -> None:
    (workspace_root / "docker-compose.yml").write_text(
        "services:\n"
        "  svc-a:\n    build: {context: ./svc-a}\n    ports: ['127.0.0.1:${A_PORT:-8000}:8000']\n"
        "  svc-b:\n    build: {context: ./svc-b}\n    ports: ['8081:8080']\n"
    )
    shell = _ready_shell()
    shell.open_ports = {8000, 8081}
    shell.expect(
        "docker compose",
        stdout=(
            '{"Service": "svc-a", "State": "running"}\n{"Service": "svc-b", "State": "exited"}\n'
        ),
    )
    result = Preflight(Workspace(workspace_root), shell, ScriptedPrompter()).run()
    rows = _rows(result)
    assert rows["port 8000"][0] is Status.OK
    assert rows["port 8081"][0] is Status.WARN
    assert not result.failed


def test_host_qbittorrent_running_warns(workspace_root: Path) -> None:
    shell = _ready_shell()
    shell.expect("tasklist", stdout="qbittorrent.exe   1234 Console\n")
    result = Preflight(Workspace(workspace_root), shell, ScriptedPrompter()).run()
    assert _rows(result)["host qBittorrent"][0] is Status.WARN
