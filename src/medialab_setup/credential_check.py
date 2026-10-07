"""Host-side credential check: read the gateway's per-key health and raise a Windows toast.

Runs from a scheduled task every half hour. A standing problem is toasted once
per day per credential; the toast's button opens a tiny .cmd that launches the
wizard on that one field. The web banner and Discord notice carry the rest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from medialab_contracts import CREDENTIAL_NAMES, CredentialState, CredentialStatus

from medialab_setup.guides import guide_for
from medialab_setup.shell import Shell
from medialab_setup.workspace import Workspace

GATEWAY_HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"
HEALTH_CREDENTIALS_KEY = "credentials"
TOAST_LEDGER_FILE = "toasts.json"
FIX_SCRIPT_TEMPLATE = "fix-{name}.cmd"
TOAST_TITLE = "medialab: a credential needs attention"
TOAST_BUTTON = "Open setup"
TOAST_APP_ID = "medialab-setup"
POWERSHELL = "powershell"
POWERSHELL_FLAGS = ("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command")


@dataclass(frozen=True)
class Problem:
    name: str
    title: str
    detail: str


def read_gateway_credentials(shell: Shell) -> dict[str, CredentialState] | None:
    """The gateway's credential map, or None when it cannot be read."""
    body = shell.http_get_text(GATEWAY_HEALTH_URL)
    if body is None:
        return None
    try:
        raw = json.loads(body).get(HEALTH_CREDENTIALS_KEY, {})
    except (json.JSONDecodeError, AttributeError):
        return None
    states: dict[str, CredentialState] = {}
    for name in CREDENTIAL_NAMES:
        if name in raw:
            try:
                states[name] = CredentialState.model_validate(raw[name])
            except ValueError:
                continue
    return states


def problems(states: dict[str, CredentialState]) -> list[Problem]:
    out: list[Problem] = []
    for name, state in states.items():
        if state.status is CredentialStatus.INVALID:
            title = guide_for(name).title if _has_guide(name) else name
            out.append(Problem(name, title, state.detail))
    return out


def _has_guide(name: str) -> bool:
    try:
        guide_for(name)
    except KeyError:
        return False
    return True


class ToastLedger:
    """Which day each credential was last toasted; one toast per credential per day."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._days: dict[str, str] = {}
        if path.exists():
            try:
                self._days = dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError):
                self._days = {}

    def should_toast(self, name: str, today: date) -> bool:
        return self._days.get(name) != today.isoformat()

    def mark(self, name: str, today: date) -> None:
        self._days[name] = today.isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._days, indent=2), encoding="utf-8")


def fix_script_path(workspace: Workspace, name: str) -> Path:
    return workspace.state_dir / FIX_SCRIPT_TEMPLATE.format(name=name)


def write_fix_script(workspace: Workspace, name: str) -> Path:
    """A double-clickable .cmd the toast button opens; it runs setup.cmd --fix <name>."""
    path = fix_script_path(workspace, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    setup_cmd = workspace.root / "setup.cmd"
    path.write_text(
        f'@echo off\r\ncall "{setup_cmd}" --fix {name}\r\n', encoding="utf-8", newline=""
    )
    return path


def toast_script(problem: Problem, fix_script: Path) -> str:
    """PowerShell that raises a WinRT toast with a button opening the fix script."""
    body = f"{problem.title} was rejected by its service"
    if problem.detail:
        body = f"{body} ({problem.detail})"
    uri = fix_script.resolve().as_uri()
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] | Out-Null\n"
        '$xml = @"\n'
        '<toast scenario="reminder">\n'
        '  <visual><binding template="ToastGeneric">\n'
        f"    <text>{_xml(TOAST_TITLE)}</text>\n"
        f"    <text>{_xml(body)}</text>\n"
        "  </binding></visual>\n"
        "  <actions>\n"
        f'    <action content="{_xml(TOAST_BUTTON)}" activationType="protocol" '
        f'arguments="{_xml(uri)}"/>\n'
        "  </actions>\n"
        "</toast>\n"
        '"@\n'
        "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        "$doc.LoadXml($xml)\n"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $doc\n"
        f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{TOAST_APP_ID}").Show($toast)\n'
    )


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def check_credentials(
    workspace: Workspace, shell: Shell, *, now: datetime | None = None
) -> tuple[list[Problem], list[str]]:
    """Read the gateway, toast each invalid credential at most once a day.
    Returns (every problem found, the names toasted this run)."""
    today = (now or datetime.now(UTC)).date()
    states = read_gateway_credentials(shell)
    if states is None:
        return [], []
    found = problems(states)
    ledger = ToastLedger(workspace.state_dir / TOAST_LEDGER_FILE)
    toasted: list[str] = []
    for problem in found:
        if not ledger.should_toast(problem.name, today):
            continue
        script = write_fix_script(workspace, problem.name)
        shell.run([POWERSHELL, *POWERSHELL_FLAGS, toast_script(problem, script)])
        ledger.mark(problem.name, today)
        toasted.append(problem.name)
    return found, toasted
