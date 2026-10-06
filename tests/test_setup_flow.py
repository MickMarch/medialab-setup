from pathlib import Path

import pytest
from fakes import FakeShell, ScriptedPrompter
from rich.console import Console

from medialab_setup.answers_file import answers_path, read_answers
from medialab_setup.checks import CheckResult, CredentialChecker
from medialab_setup.collect import Mode
from medialab_setup.guides import Check, guide_for
from medialab_setup.jellyfin_client import JellyfinClient, Library
from medialab_setup.preflight import JELLYFIN_HEALTH_URL, PreflightError
from medialab_setup.scripts import DOCTOR_SCRIPT, PROVISION_SCRIPT, ScriptError
from medialab_setup.setup_flow import (
    MINIMUM_FREE_BYTES,
    VERIFY_INTERVAL_SECONDS,
    VERIFY_WINDOW_SECONDS,
    Phase,
    SetupContext,
    SetupOptions,
    VerifyError,
    media_folders,
    run_setup,
)
from medialab_setup.workspace import Workspace

PROVISION = Path(PROVISION_SCRIPT).name
DOCTOR = Path(DOCTOR_SCRIPT).name
REAL_SERVICES = ("torrent-downloader", "medialab-jellyfin", "medialab-bot", "medialab-web")
REQUIRED_TITLES = (
    "tmdb_api_key",
    "jellyfin_api_key",
    "discord_token",
    "discord_guild_id",
    "web_password",
    "wireguard_private_key",
)


class AlwaysOkChecker(CredentialChecker):
    def run(self, check: Check, value: str) -> CheckResult:
        return CheckResult(ok=True, detail="ok")


class FakeJellyfin(JellyfinClient):
    instances: list["FakeJellyfin"] = []

    def __init__(self, api_key: str, base_url: str = "") -> None:
        super().__init__(api_key, base_url or "http://127.0.0.1:8096")
        self.created: list[str] = []
        FakeJellyfin.instances.append(self)

    def list_libraries(self) -> list[Library]:
        return []

    def create_library(self, name: str, collection_type: str, path: str) -> None:
        self.created.append(name)


def _real_workspace(root: Path) -> Workspace:
    compose = "services:\n" + "".join(
        f"  {svc}:\n    build:\n      context: ./{svc}\n" for svc in REAL_SERVICES
    )
    (root / "docker-compose.yml").write_text(compose)
    examples = {
        "torrent-downloader": "API_KEY=\nQB_API_KEY=\nTMDB_API_KEY=\n",
        "medialab-jellyfin": "JELLYFIN_HOST=127.0.0.1\nJELLYFIN_API_KEY=\nAPI_KEY=\n",
        "medialab-bot": "DISCORD_TOKEN=\nDISCORD_GUILD_ID=\nORCHESTRATOR_API_KEY=\n",
        "medialab-web": "ORCHESTRATOR_API_KEY=\nWEB_PASSWORD=\nWEB_SECRET_KEY=\n",
    }
    for svc, text in examples.items():
        (root / svc).mkdir()
        (root / svc / ".env.example").write_text(text)
    return Workspace(root)


def _ready_shell() -> FakeShell:
    shell = FakeShell(http={JELLYFIN_HEALTH_URL: "Healthy"})
    shell.expect("git -C", stdout=" abc x (v1)\n")
    shell.expect("docker info", stdout="28.0.0\n")
    return shell


def _ctx(root: Path, media: Path, **options: object) -> SetupContext:
    script = {guide_for(name).title: [f"value-{name}"] for name in REQUIRED_TITLES}
    script[guide_for("media_host_dir").title] = [media.as_posix()]
    return SetupContext(
        workspace=_real_workspace(root),
        options=SetupOptions(**options),  # type: ignore[arg-type]
        shell=_ready_shell(),
        prompter=ScriptedPrompter(script),
        checker=AlwaysOkChecker(),
        console=Console(record=True, width=400),
        make_jellyfin_client=FakeJellyfin,
    )


def test_media_folders_follow_the_contracts_layout() -> None:
    folders = {p.as_posix() for p in media_folders("F:/Media")}
    assert folders == {
        "F:/Media/Movies",
        "F:/Media/Shows",
        "F:/Media/_incoming/Movies",
        "F:/Media/_incoming/Shows",
    }


def test_full_run_writes_env_files_folders_and_answers(
    workspace_root: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    ctx = _ctx(workspace_root, media)
    run_setup(ctx)
    assert (workspace_root / "medialab-web" / ".env").exists()
    assert (workspace_root / "gluetun" / "vpn.env").exists()
    assert (media / "_incoming" / "Shows").is_dir()
    saved = read_answers(answers_path(workspace_root))
    assert saved.media_host_dir == media.as_posix()
    assert saved.tmdb_api_key is None


def test_dry_run_writes_nothing(workspace_root: Path, tmp_path: Path) -> None:
    media = tmp_path / "media"
    ctx = _ctx(workspace_root, media, dry_run=True)
    before = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))
    run_setup(ctx)
    after = sorted(p.relative_to(workspace_root) for p in workspace_root.rglob("*"))
    assert before == after
    assert not media.exists()
    assert "Dry run" in ctx.console.export_text()


def test_stop_after_preflight_asks_nothing(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media", stop_after=Phase.PREFLIGHT)
    run_setup(ctx)
    assert ctx.prompter.asked == []  # type: ignore[attr-defined]
    assert ctx.collected is None


def test_preflight_failure_stops_before_collect(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media")
    ctx.shell.expect("docker info", returncode=1)  # type: ignore[attr-defined]
    with pytest.raises(PreflightError, match="docker engine"):
        run_setup(ctx)
    assert ctx.collected is None


def _streamed(ctx: SetupContext) -> list[str]:
    return [" ".join(command) for command in ctx.shell.streams]  # type: ignore[attr-defined]


def test_full_run_drives_scripts_compose_jellyfin_and_doctor(
    workspace_root: Path, tmp_path: Path
) -> None:
    FakeJellyfin.instances.clear()
    ctx = _ctx(workspace_root, tmp_path / "media")
    run_setup(ctx)
    streamed = _streamed(ctx)
    assert any("medialab-build.sh" in c for c in streamed)
    assert any(PROVISION in c for c in streamed)
    assert any("docker compose" in c and c.endswith("up -d") for c in streamed)
    assert any(DOCTOR in c for c in streamed)
    assert FakeJellyfin.instances[0].created == ["Movies", "Shows"]
    assert streamed.index(next(c for c in streamed if PROVISION in c)) < streamed.index(
        next(c for c in streamed if DOCTOR in c)
    )


def test_dry_run_streams_nothing(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media", dry_run=True)
    run_setup(ctx)
    assert _streamed(ctx) == []
    assert "medialab-build.sh" in ctx.console.export_text()


def test_failing_script_stops_the_run(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media")
    ctx.shell.expect_stream(PROVISION, 1)  # type: ignore[attr-defined]
    with pytest.raises(ScriptError, match=PROVISION):
        run_setup(ctx)
    assert not any("docker compose" in c for c in _streamed(ctx))


def test_verify_retries_until_green(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media")
    ctx.shell.expect_stream(DOCTOR, 1, 1, 0)  # type: ignore[attr-defined]
    run_setup(ctx)
    assert ctx.shell.slept == [VERIFY_INTERVAL_SECONDS, VERIFY_INTERVAL_SECONDS]  # type: ignore[attr-defined]
    assert "Doctor green." in ctx.console.export_text()


def test_verify_gives_up_after_the_window(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media")
    ctx.shell.expect_stream(DOCTOR, 1)  # type: ignore[attr-defined]
    with pytest.raises(VerifyError):
        run_setup(ctx)
    assert sum(ctx.shell.slept) >= VERIFY_WINDOW_SECONDS  # type: ignore[attr-defined]


def test_skip_host_skips_only_host(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media", skip_host=True)
    run_setup(ctx)
    text = ctx.console.export_text()
    assert "Skipped (--skip-host)" in text
    assert "Doctor green." in text


def test_stop_after_generate_runs_no_script(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media", stop_after=Phase.GENERATE)
    run_setup(ctx)
    assert _streamed(ctx) == []


def test_low_disk_space_is_a_warning(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media", dry_run=True)
    ctx.shell.free_bytes = MINIMUM_FREE_BYTES - 1  # type: ignore[attr-defined]
    run_setup(ctx)
    assert "free on the media drive" in ctx.console.export_text()


def test_custom_mode_is_threaded_through(workspace_root: Path, tmp_path: Path) -> None:
    ctx = _ctx(workspace_root, tmp_path / "media", dry_run=True, mode=Mode.CUSTOM)
    run_setup(ctx)
    assert "medialab-jellyfin: JELLYFIN_HOST" not in ctx.prompter.asked  # type: ignore[attr-defined]
    assert "torrent-downloader: QB_API_KEY" not in ctx.prompter.asked  # type: ignore[attr-defined]
    assert guide_for("timezone").title in ctx.prompter.asked  # type: ignore[attr-defined]
