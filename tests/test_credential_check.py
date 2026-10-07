from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fakes import FakeShell
from medialab_contracts import CREDENTIAL_JELLYFIN_API_KEY, CREDENTIAL_TMDB_API_KEY

from medialab_setup.credential_check import (
    GATEWAY_HEALTH_URL,
    TOAST_BUTTON,
    TOAST_LEDGER_FILE,
    Problem,
    check_credentials,
    fix_script_path,
    toast_script,
)
from medialab_setup.workspace import Workspace

DAY_ONE = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
DAY_ONE_LATER = datetime(2026, 10, 7, 21, 0, tzinfo=UTC)
DAY_TWO = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def _health(**states: str) -> str:
    return json.dumps(
        {
            "status": "online",
            "credentials": {k: {"status": v, "detail": "HTTP 401"} for k, v in states.items()},
        }
    )


def _toasts(shell: FakeShell) -> list[str]:
    return [
        args[-1]
        for args in shell.runs
        if args[0] == "powershell" and "ToastNotification" in args[-1]
    ]


def test_nothing_happens_when_all_credentials_are_ok(workspace_root: Path) -> None:
    shell = FakeShell(http={GATEWAY_HEALTH_URL: _health(tmdb_api_key="ok", jellyfin_api_key="ok")})
    found, toasted = check_credentials(Workspace(workspace_root), shell, now=DAY_ONE)
    assert found == [] and toasted == []
    assert _toasts(shell) == []


def test_gateway_unreachable_is_silent(workspace_root: Path) -> None:
    shell = FakeShell(http={})
    found, toasted = check_credentials(Workspace(workspace_root), shell, now=DAY_ONE)
    assert found == [] and toasted == []


def test_invalid_credential_toasts_once_per_day_with_a_fix_button(workspace_root: Path) -> None:
    shell = FakeShell(http={GATEWAY_HEALTH_URL: _health(tmdb_api_key="invalid", qb_api_key="ok")})
    workspace = Workspace(workspace_root)
    found, toasted = check_credentials(workspace, shell, now=DAY_ONE)
    assert [p.name for p in found] == [CREDENTIAL_TMDB_API_KEY]
    assert toasted == [CREDENTIAL_TMDB_API_KEY]
    toast = _toasts(shell)[0]
    assert "TMDB API key (v3)" in toast and "HTTP 401" in toast
    assert TOAST_BUTTON in toast
    script = fix_script_path(workspace, CREDENTIAL_TMDB_API_KEY)
    assert script.exists()
    assert f"--fix {CREDENTIAL_TMDB_API_KEY}" in script.read_text()
    assert script.resolve().as_uri() in toast
    assert (workspace.state_dir / TOAST_LEDGER_FILE).exists()

    _, again = check_credentials(workspace, shell, now=DAY_ONE_LATER)
    assert again == []
    assert len(_toasts(shell)) == 1

    _, next_day = check_credentials(workspace, shell, now=DAY_TWO)
    assert next_day == [CREDENTIAL_TMDB_API_KEY]
    assert len(_toasts(shell)) == 2


def test_each_invalid_credential_gets_its_own_toast(workspace_root: Path) -> None:
    shell = FakeShell(
        http={GATEWAY_HEALTH_URL: _health(tmdb_api_key="invalid", jellyfin_api_key="invalid")}
    )
    _, toasted = check_credentials(Workspace(workspace_root), shell, now=DAY_ONE)
    assert set(toasted) == {CREDENTIAL_TMDB_API_KEY, CREDENTIAL_JELLYFIN_API_KEY}
    assert len(_toasts(shell)) == 2


def test_toast_script_escapes_xml() -> None:
    script = toast_script(Problem("x", "A & B <c>", 'say "hi"'), Path("C:/t/fix-x.cmd"))
    assert "A &amp; B &lt;c&gt;" in script
    assert "&quot;hi&quot;" in script
