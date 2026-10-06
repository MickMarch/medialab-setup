"""Phase Host: the steps in docs/host-setup.md, each a read-only check then an apply.

Elevated applies are batched into one PowerShell child so UAC prompts once.
Automatic logon and Docker Desktop's own autostart switch are guided manual
steps: the first needs the account password typed by its owner, the second
must be changed while Docker Desktop is quit, which it never is while setup
runs. Both are rechecked after the operator confirms.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PureWindowsPath

from medialab_setup.prompts import Prompter, UrlOpener, open_in_browser
from medialab_setup.scripts import bash_executable
from medialab_setup.shell import Shell
from medialab_setup.workspace import Workspace

POWERSHELL = "powershell"
POWERSHELL_FLAGS = ("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass")
ELEVATED_SCRIPT_NAME = "host-steps.ps1"
AUTOLOGON_URL = "https://learn.microsoft.com/sysinternals/downloads/autologon"
DOCKER_SETTINGS_HINT = "Docker Desktop > Settings > General > Start Docker Desktop when you sign in"
JELLYFIN_TASK = "medialab-jellyfin-server"
LOCK_TASK = "medialab-lock-at-logon"
DOCTOR_TASK = "medialab-doctor-after-logon"
FIREWALL_RULE = "medialab-web LAN"
DOCTOR_BOOT_LOG = ".doctor-boot.log"
WEB_PORT = 8081


class Outcome(str, Enum):
    OK = "ok"
    APPLIED = "applied"
    MANUAL = "manual"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class HostStep:
    name: str
    check: str
    apply: str | None
    elevated: bool = False
    manual_text: str | None = None
    manual_url: str | None = None


@dataclass(frozen=True)
class HostRow:
    outcome: Outcome
    name: str
    detail: str


def git_bash_path(path: Path) -> str:
    """C:\\x\\y as Git Bash spells it: /c/x/y. Parsed as a Windows path on any OS."""
    windows = PureWindowsPath(str(path))
    drive = windows.drive.rstrip(":").lower()
    rest = "/".join(windows.parts[1:])
    return f"/{drive}/{rest}"


TASKS_DIR = r"C:\Windows\System32\Tasks"


def _task_exists(name: str) -> str:
    """Visible through Get-ScheduledTask, or, for a SYSTEM task a user may not read,
    through the task file: a missing file is ItemNotFound, an unreadable one is access denied."""
    return (
        f'if (Get-ScheduledTask -TaskName "{name}" -ErrorAction SilentlyContinue) {{ "ok" }} '
        f'else {{ try {{ Get-Item "{TASKS_DIR}\\{name}" -ErrorAction Stop | Out-Null; "ok" }} '
        f'catch [System.UnauthorizedAccessException] {{ "ok" }} catch {{ }} }}'
    )


def _firewall_rule_exists(name: str) -> str:
    """netsh exits 0 only when the rule exists; Get-NetFirewallRule needs elevation."""
    return f'netsh advfirewall firewall show rule name="{name}" | Out-Null; if ($LASTEXITCODE -eq 0) {{ "ok" }}'


def host_steps(workspace: Workspace, shell: Shell) -> tuple[HostStep, ...]:
    repo = git_bash_path(workspace.root)
    bash = bash_executable(shell)
    return (
        HostStep(
            name="Jellyfin at boot (SYSTEM task)",
            check=_task_exists(JELLYFIN_TASK),
            apply=(
                '$action = New-ScheduledTaskAction -Execute "C:\\Program Files\\Jellyfin\\Server\\jellyfin.exe" '
                "-Argument '--service --datadir \"C:\\ProgramData\\Jellyfin\\Server\"' "
                '-WorkingDirectory "C:\\Program Files\\Jellyfin\\Server"\n'
                "$trigger = New-ScheduledTaskTrigger -AtStartup\n"
                '$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\\SYSTEM" '
                "-LogonType ServiceAccount -RunLevel Highest\n"
                "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
                "-StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) "
                "-ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew\n"
                f'Register-ScheduledTask -TaskName "{JELLYFIN_TASK}" -Action $action -Trigger $trigger '
                "-Principal $principal -Settings $settings -Force | Out-Null\n"
            ),
            elevated=True,
        ),
        HostStep(
            name="Jellyfin tray login autostart disabled",
            check=(
                '$v = (Get-ItemProperty "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run" '
                "-Name JellyfinTray -ErrorAction SilentlyContinue).JellyfinTray\n"
                'if ($null -eq $v -or $v[0] -eq 3) { "ok" }'
            ),
            apply=(
                'New-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run" '
                "-Name JellyfinTray -PropertyType Binary -Value ([byte[]](3,0,0,0,0,0,0,0,0,0,0,0)) -Force | Out-Null\n"
            ),
        ),
        HostStep(
            name="Lock desktop at logon",
            check=_task_exists(LOCK_TASK),
            apply=(
                '$action = New-ScheduledTaskAction -Execute "rundll32.exe" -Argument "user32.dll,LockWorkStation"\n'
                '$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\\$env:USERNAME"\n'
                '$trigger.Delay = "PT10S"\n'
                f'Register-ScheduledTask -TaskName "{LOCK_TASK}" -Action $action -Trigger $trigger '
                "-RunLevel Limited -Force | Out-Null\n"
            ),
            elevated=True,
        ),
        HostStep(
            name="Automatic logon",
            check=(
                '$w = Get-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon"\n'
                'if ($w.AutoAdminLogon -eq "1") { "ok" }'
            ),
            apply=None,
            manual_text=(
                "Run Sysinternals Autologon, enter this account and its password, click Enable. "
                "The credential lands in the LSA secret store; this tool never collects it."
            ),
            manual_url=AUTOLOGON_URL,
        ),
        HostStep(
            name="Docker Desktop autostart switch",
            check=(
                '$f = "$env:APPDATA\\Docker\\settings-store.json"\n'
                'if ((Test-Path $f) -and ((Get-Content $f -Raw | ConvertFrom-Json).AutoStart)) { "ok" }'
            ),
            apply=None,
            manual_text=f"Turn on {DOCKER_SETTINGS_HINT}, then Apply.",
        ),
        HostStep(
            name="Doctor after logon",
            check=_task_exists(DOCTOR_TASK),
            apply=(
                f'$bash = "{bash}"\n'
                f"$action = New-ScheduledTaskAction -Execute $bash -Argument "
                f"\"-lc 'cd {repo} && {{ date; bin/medialab-doctor.sh; echo exit=`$?; }} "
                f"> {DOCTOR_BOOT_LOG} 2>&1'\"\n"
                '$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\\$env:USERNAME"\n'
                '$trigger.Delay = "PT4M"\n'
                f'Register-ScheduledTask -TaskName "{DOCTOR_TASK}" -Action $action -Trigger $trigger '
                "-RunLevel Limited -Force | Out-Null\n"
            ),
        ),
        HostStep(
            name="Web UI reachable from the LAN",
            check=_firewall_rule_exists(FIREWALL_RULE),
            apply=(
                f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
                f"protocol=TCP localport={WEB_PORT} profile=private | Out-Null\n"
            ),
            elevated=True,
        ),
    )


class HostPhase:
    def __init__(
        self,
        workspace: Workspace,
        shell: Shell,
        prompter: Prompter,
        *,
        dry_run: bool = False,
        assume_yes: bool = False,
        interactive: bool = True,
        opener: UrlOpener = open_in_browser,
    ) -> None:
        self.workspace = workspace
        self.shell = shell
        self.prompter = prompter
        self.dry_run = dry_run
        self.assume_yes = assume_yes
        self.interactive = interactive
        self.opener = opener

    def run(self) -> list[HostRow]:
        steps = host_steps(self.workspace, self.shell)
        rows: dict[str, HostRow] = {}
        elevated_batch: list[HostStep] = []
        for step in steps:
            if self._check(step):
                rows[step.name] = HostRow(Outcome.OK, step.name, "already in place")
                continue
            if step.apply is None:
                rows[step.name] = self._manual(step)
                continue
            self.prompter.note(f"[bold]{step.name}[/bold]\n{step.apply}")
            if self.dry_run:
                rows[step.name] = HostRow(Outcome.SKIPPED, step.name, "dry run")
                continue
            if not self._confirm(
                f"Apply '{step.name}'{' (needs elevation)' if step.elevated else ''}?"
            ):
                rows[step.name] = HostRow(Outcome.SKIPPED, step.name, "declined")
                continue
            if step.elevated:
                elevated_batch.append(step)
            else:
                rows[step.name] = self._apply_now(step)
        if elevated_batch:
            rows.update(self._apply_elevated(elevated_batch))
        return [rows[step.name] for step in steps]

    def _check(self, step: HostStep) -> bool:
        completed = self.shell.run([POWERSHELL, *POWERSHELL_FLAGS, "-Command", step.check])
        return completed.returncode == 0 and completed.stdout.strip() == "ok"

    def _confirm(self, message: str) -> bool:
        if self.assume_yes:
            return True
        if not self.interactive:
            return False
        return self.prompter.confirm(message, default=True)

    def _manual(self, step: HostStep) -> HostRow:
        self.prompter.note(f"[bold]{step.name}[/bold]\n{step.manual_text}")
        if self.dry_run or not self.interactive:
            return HostRow(Outcome.MANUAL, step.name, step.manual_text or "")
        if step.manual_url and self.prompter.confirm(f"Open {step.manual_url}?", default=True):
            self.opener(step.manual_url)
        self.prompter.confirm("Done? Enter to recheck.", default=True)
        if self._check(step):
            return HostRow(Outcome.OK, step.name, "confirmed")
        return HostRow(Outcome.MANUAL, step.name, "still not in place; re-run setup after doing it")

    def _apply_now(self, step: HostStep) -> HostRow:
        assert step.apply is not None
        completed = self.shell.run([POWERSHELL, *POWERSHELL_FLAGS, "-Command", step.apply])
        if completed.returncode != 0 or not self._check(step):
            return HostRow(
                Outcome.FAILED, step.name, completed.stderr.strip() or "check still failing"
            )
        return HostRow(Outcome.APPLIED, step.name, "applied")

    def _apply_elevated(self, steps: list[HostStep]) -> dict[str, HostRow]:
        script_path = self.workspace.state_dir / ELEVATED_SCRIPT_NAME
        script_path.parent.mkdir(parents=True, exist_ok=True)
        body = "$ErrorActionPreference = 'Stop'\n" + "\n".join(step.apply or "" for step in steps)
        script_path.write_text(body, encoding="utf-8", newline="\n")
        self.shell.run_elevated(script_path)
        rows: dict[str, HostRow] = {}
        for step in steps:
            if self._check(step):
                rows[step.name] = HostRow(Outcome.APPLIED, step.name, "applied (elevated)")
            else:
                rows[step.name] = HostRow(
                    Outcome.FAILED, step.name, "check still failing after elevated run"
                )
        return rows
