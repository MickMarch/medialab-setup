import subprocess
from pathlib import Path

from fakes import FakeShell, ScriptedPrompter

from medialab_setup.host import (
    DOCTOR_TASK,
    FIREWALL_RULE,
    JELLYFIN_TASK,
    LOCK_TASK,
    HostPhase,
    HostRow,
    Outcome,
    git_bash_path,
    host_steps,
)
from medialab_setup.scripts import GIT_BASH
from medialab_setup.workspace import Workspace

ALL_OK_FRAGMENTS = (
    JELLYFIN_TASK,
    "JellyfinTray",
    LOCK_TASK,
    "AutoAdminLogon",
    "AutoStart",
    DOCTOR_TASK,
    FIREWALL_RULE,
)


def _shell(ok: set[str]) -> FakeShell:
    shell = FakeShell(existing_paths={GIT_BASH})
    for fragment in ALL_OK_FRAGMENTS:
        shell.expect(fragment, stdout="ok\n" if fragment in ok else "")
    return shell


def _outcomes(rows: list[HostRow]) -> dict[str, Outcome]:
    return {row.name: row.outcome for row in rows}


def test_git_bash_path_spells_drive_lowercase() -> None:
    assert git_bash_path(Path(r"C:\Users\x\medialab")) == "/c/Users/x/medialab"


def test_steps_embed_workspace_and_bash(workspace_root: Path) -> None:
    steps = host_steps(Workspace(workspace_root), FakeShell(existing_paths={GIT_BASH}))
    doctor = next(step for step in steps if DOCTOR_TASK in step.check)
    assert git_bash_path(workspace_root) in (doctor.apply or "")
    assert str(GIT_BASH) in (doctor.apply or "")
    manual = [step.name for step in steps if step.apply is None]
    assert manual == ["Automatic logon", "Docker Desktop autostart switch"]


def test_everything_in_place_is_all_ok(workspace_root: Path) -> None:
    shell = _shell(set(ALL_OK_FRAGMENTS))
    rows = HostPhase(Workspace(workspace_root), shell, ScriptedPrompter()).run()
    assert set(_outcomes(rows).values()) == {Outcome.OK}
    assert shell.elevated_scripts == []


def test_dry_run_checks_but_applies_nothing(workspace_root: Path) -> None:
    shell = _shell(set())
    prompter = ScriptedPrompter(confirms=True)
    rows = HostPhase(Workspace(workspace_root), shell, prompter, dry_run=True).run()
    outcomes = _outcomes(rows)
    assert outcomes["Jellyfin at boot (SYSTEM task)"] is Outcome.SKIPPED
    assert outcomes["Automatic logon"] is Outcome.MANUAL
    assert shell.elevated_scripts == []
    assert all(args[0] == "powershell" and "-Command" in args for args in shell.runs)
    assert any("Register-ScheduledTask" in note for note in prompter.notes)


def test_elevated_steps_are_batched_into_one_script(workspace_root: Path) -> None:
    shell = _shell({"JellyfinTray", "AutoAdminLogon", "AutoStart", DOCTOR_TASK})
    prompter = ScriptedPrompter(confirms=True)

    phase = HostPhase(Workspace(workspace_root), shell, prompter)
    original = shell.run_elevated

    def elevate_and_succeed(script_path: Path) -> int:
        code = original(script_path)
        for fragment in (JELLYFIN_TASK, LOCK_TASK, FIREWALL_RULE):
            shell.expect(fragment, stdout="ok\n")
        return code

    shell.run_elevated = elevate_and_succeed  # type: ignore[method-assign]
    rows = phase.run()
    assert len(shell.elevated_scripts) == 1
    script = shell.elevated_scripts[0]
    assert JELLYFIN_TASK in script and LOCK_TASK in script and FIREWALL_RULE in script
    outcomes = _outcomes(rows)
    assert outcomes["Jellyfin at boot (SYSTEM task)"] is Outcome.APPLIED
    assert outcomes["Web UI reachable from the LAN"] is Outcome.APPLIED
    assert (workspace_root / ".medialab-setup" / "host-steps.ps1").exists()


def test_declined_step_is_skipped(workspace_root: Path) -> None:
    shell = _shell(set(ALL_OK_FRAGMENTS) - {FIREWALL_RULE})
    rows = HostPhase(Workspace(workspace_root), shell, ScriptedPrompter(confirms=False)).run()
    assert _outcomes(rows)["Web UI reachable from the LAN"] is Outcome.SKIPPED
    assert shell.elevated_scripts == []


def test_non_elevated_step_applies_directly_and_rechecks(workspace_root: Path) -> None:
    shell = _shell(set(ALL_OK_FRAGMENTS) - {DOCTOR_TASK})
    applied: list[str] = []
    original_run = shell.run

    def run(args: list[str], *, timeout: float = 0) -> subprocess.CompletedProcess[str]:
        if "Register-ScheduledTask" in args[-1] and DOCTOR_TASK in args[-1]:
            applied.append(args[-1])
            shell.expect(DOCTOR_TASK, stdout="ok\n")
        return original_run(args, timeout=timeout)

    shell.run = run  # type: ignore[method-assign]
    rows = HostPhase(Workspace(workspace_root), shell, ScriptedPrompter(confirms=True)).run()
    assert len(applied) == 1
    assert _outcomes(rows)["Doctor after logon"] is Outcome.APPLIED
    assert shell.elevated_scripts == []


def test_manual_step_opens_url_and_rechecks(workspace_root: Path) -> None:
    shell = _shell(set(ALL_OK_FRAGMENTS) - {"AutoAdminLogon"})
    opened: list[str] = []
    prompter = ScriptedPrompter(confirms=True)
    rows = HostPhase(Workspace(workspace_root), shell, prompter, opener=opened.append).run()
    assert any("sysinternals" in url for url in opened)
    assert _outcomes(rows)["Automatic logon"] is Outcome.MANUAL
    assert any("password" in note for note in prompter.notes)


def test_non_interactive_never_applies(workspace_root: Path) -> None:
    shell = _shell(set())
    rows = HostPhase(Workspace(workspace_root), shell, ScriptedPrompter(), interactive=False).run()
    assert Outcome.APPLIED not in _outcomes(rows).values()
    assert shell.elevated_scripts == []
