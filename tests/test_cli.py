from pathlib import Path

import pytest
from fakes import FakeShell
from typer.testing import CliRunner

from medialab_setup import cli
from medialab_setup.answers import Answers
from medialab_setup.answers_file import write_answers
from medialab_setup.cli import VERSION_UNKNOWN, app, installed_version
from medialab_setup.preflight import JELLYFIN_HEALTH_URL

runner = CliRunner()

REAL_SERVICES = ("torrent-downloader", "medialab-jellyfin", "medialab-bot", "medialab-web")
COMPLETE_ENVS = {
    "torrent-downloader": "TMDB_API_KEY={tmdb}\n",
    "medialab-jellyfin": "JELLYFIN_API_KEY=j\n",
    "medialab-bot": "DISCORD_TOKEN=d\nDISCORD_GUILD_ID=1\n",
    "medialab-web": "WEB_PASSWORD=w\n",
}


def _real_workspace(root: Path, tmdb: str = "t") -> None:
    """Point the fixture compose at the real service names so BINDINGS apply."""
    compose = "services:\n" + "".join(
        f"  {svc}:\n    build:\n      context: ./{svc}\n" for svc in REAL_SERVICES
    )
    (root / "docker-compose.yml").write_text(compose)
    (root / ".env").write_text("MEDIA_HOST_DIR=E:/Media\n")
    for svc in REAL_SERVICES:
        (root / svc).mkdir()
        (root / svc / ".env.example").write_text(COMPLETE_ENVS[svc].format(tmdb=""))
        (root / svc / ".env").write_text(COMPLETE_ENVS[svc].format(tmdb=tmdb))
    (root / "gluetun" / "vpn.env").write_text("WIREGUARD_PRIVATE_KEY=k\n")


def test_help_lists_tool_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "medialab-setup" in result.output


def test_version_prints_installed_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == installed_version()
    assert result.output.strip() != ""


def test_unknown_version_is_a_named_constant() -> None:
    assert VERSION_UNKNOWN == "unknown"


def test_plan_without_a_terminal_and_missing_values_exits_with_usage(
    workspace_root: Path,
) -> None:
    result = runner.invoke(app, ["plan", "--workspace", str(workspace_root)])
    assert result.exit_code == 2
    assert "missing values" in result.output


def test_plan_with_complete_existing_env_writes_nothing(workspace_root: Path) -> None:
    _real_workspace(workspace_root)
    answers = workspace_root / "answers.toml"
    write_answers(answers, Answers(timezone="UTC"), backup_dir=workspace_root / "bk")
    before = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))
    result = runner.invoke(
        app, ["plan", "--workspace", str(workspace_root), "--answers", str(answers)]
    )
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "Answers" in result.output and "Files" in result.output
    after = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))
    assert before == after


def test_plan_output_never_shows_a_secret(workspace_root: Path) -> None:
    _real_workspace(workspace_root, tmdb="tmdb-secret-value")
    result = runner.invoke(app, ["plan", "--workspace", str(workspace_root)])
    assert result.exit_code == 0, result.output
    assert "tmdb-secret-value" not in result.output


def test_setup_dry_run_with_complete_env_exits_zero(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _real_workspace(workspace_root)
    shell = FakeShell(http={JELLYFIN_HEALTH_URL: "Healthy"})
    shell.expect("git -C", stdout=" abc x (v1)\n")
    shell.expect("docker info", stdout="28.0.0\n")
    monkeypatch.setattr(cli, "make_shell", lambda: shell)
    result = runner.invoke(app, ["setup", "--workspace", str(workspace_root), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Preflight" in result.output
    assert "Dry run" in result.output


def test_setup_refuses_unimplemented_stop_after(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _real_workspace(workspace_root)
    monkeypatch.setattr(cli, "make_shell", FakeShell)
    result = runner.invoke(
        app, ["setup", "--workspace", str(workspace_root), "--stop-after", "verify"]
    )
    assert result.exit_code == 2
    assert "not implemented" in result.output
