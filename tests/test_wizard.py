from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeShell
from fastapi.testclient import TestClient
from markupsafe import escape

from medialab_setup.bindings import ASKED_FIELDS, REQUIRED_FIELDS
from medialab_setup.checks import CheckResult, CredentialChecker
from medialab_setup.collect import CollectError
from medialab_setup.envfile import parse_env_values
from medialab_setup.guides import Check, guide_for
from medialab_setup.jellyfin_client import JellyfinClient, Library
from medialab_setup.preflight import JELLYFIN_HEALTH_URL
from medialab_setup.wizard.app import (
    IDLE_TIMEOUT_SECONDS,
    TOKEN_COOKIE,
    WizardState,
    create_app,
    should_stop,
)
from medialab_setup.wizard.log import LineLog
from medialab_setup.wizard.prompter import WebPrompter, extra_field_name
from medialab_setup.wizard.runner import RunState, start_run
from medialab_setup.workspace import Workspace

REAL_SERVICES = ("torrent-downloader", "medialab-jellyfin", "medialab-bot", "medialab-web")
EXAMPLES = {
    "torrent-downloader": (
        "API_KEY=\nQB_API_KEY=\nTMDB_API_KEY=\n# Minimum seeders.\nMINIMUM_SEEDERS=10\n"
    ),
    "medialab-jellyfin": "JELLYFIN_HOST=127.0.0.1\nJELLYFIN_API_KEY=\nAPI_KEY=\n",
    "medialab-bot": "DISCORD_TOKEN=\nDISCORD_GUILD_ID=\nORCHESTRATOR_API_KEY=\n",
    "medialab-web": "ORCHESTRATOR_API_KEY=\nWEB_PASSWORD=\nWEB_SECRET_KEY=\n",
}


class ScriptedChecker(CredentialChecker):
    def __init__(self, bad: set[str] | None = None, offline: bool = False) -> None:
        super().__init__()
        self.bad = bad or set()
        self.offline = offline

    def run(self, check: Check, value: str) -> CheckResult:
        if self.offline:
            return CheckResult.offline(OSError("down"))
        if value in self.bad:
            return CheckResult(ok=False, detail="rejected (HTTP 401)")
        return CheckResult(ok=True, detail="accepted")


class FakeJellyfin(JellyfinClient):
    def list_libraries(self) -> list[Library]:
        return [Library("Movies", "movies", ("F:/Media/Movies",))]

    def create_library(self, name: str, collection_type: str, path: str) -> None:
        return None


def _workspace(root: Path) -> Workspace:
    compose = "services:\n" + "".join(
        f"  {svc}:\n    build:\n      context: ./{svc}\n" for svc in REAL_SERVICES
    )
    (root / "docker-compose.yml").write_text(compose)
    for svc, text in EXAMPLES.items():
        (root / svc).mkdir()
        (root / svc / ".env.example").write_text(text)
    return Workspace(root)


def _shell() -> FakeShell:
    shell = FakeShell(http={JELLYFIN_HEALTH_URL: "Healthy"})
    shell.expect("git -C", stdout=" abc x (v1)\n")
    shell.expect("docker info", stdout="28.0.0\n")
    return shell


def _client(root: Path, checker: CredentialChecker | None = None) -> tuple[TestClient, WizardState]:
    root.mkdir(exist_ok=True)
    state = WizardState(
        workspace=_workspace(root),
        shell=_shell(),
        checker=checker or ScriptedChecker(),
        make_jellyfin_client=FakeJellyfin,
    )
    client = TestClient(create_app(state), follow_redirects=False)
    return client, state


def _enter(client: TestClient, state: WizardState) -> None:
    response = client.get(f"/?t={state.token}")
    assert response.status_code == 303
    assert client.cookies.get(TOKEN_COOKIE) == state.token


def _full_form(media: Path) -> dict[str, str]:
    form = {name: f"value-{name}" for name in REQUIRED_FIELDS}
    form["media_host_dir"] = media.as_posix()
    return form


def test_entry_requires_the_token(workspace_root: Path) -> None:
    client, state = _client(workspace_root)
    assert client.get("/").status_code == 403
    assert client.get("/?t=wrong").status_code == 403
    assert client.get("/prereqs").status_code == 403
    _enter(client, state)
    assert client.get("/prereqs").status_code == 200


def test_prereqs_page_lists_preflight_rows(workspace_root: Path) -> None:
    client, state = _client(workspace_root)
    _enter(client, state)
    html = client.get("/prereqs").text
    for name in ("Git", "uv", "Docker Desktop", "Jellyfin Server", "compose project"):
        assert name in html
    assert "Continue" in html


def test_missing_prereq_shows_install_button_and_installs(workspace_root: Path) -> None:
    client, state = _client(workspace_root)
    state.shell.commands.discard("uv")  # type: ignore[attr-defined]
    state.shell.install_adds["astral-sh.uv"] = "uv"  # type: ignore[attr-defined]
    _enter(client, state)
    html = client.get("/prereqs").text
    assert "Install" in html and "Fix the failing rows" in html
    row = client.post("/prereqs/install/uv").text
    assert "installed via winget" in row


def test_credentials_page_has_a_field_and_help_per_asked_value(workspace_root: Path) -> None:
    client, state = _client(workspace_root)
    _enter(client, state)
    html = client.get("/credentials").text
    for name in ASKED_FIELDS:
        guide = guide_for(name)
        assert f'name="{name}"' in html
        assert guide.title in html
        assert str(escape(guide.steps[0])) in html
        if guide.url:
            assert guide.url in html
    for name in REQUIRED_FIELDS:
        assert f'id="field-{name}"' in html
    assert 'type="password"' in html
    assert "value-" not in html


def test_advanced_section_lists_unbound_template_keys_with_help(workspace_root: Path) -> None:
    client, state = _client(workspace_root)
    _enter(client, state)
    html = client.get("/credentials").text
    assert extra_field_name("torrent-downloader", "MINIMUM_SEEDERS") in html
    assert "Minimum seeders." in html
    assert extra_field_name("torrent-downloader", "TMDB_API_KEY") not in html


def test_blur_check_states(workspace_root: Path) -> None:
    client, state = _client(workspace_root, ScriptedChecker(bad={"bad"}))
    _enter(client, state)
    assert "accepted" in client.post("/check/tmdb_api_key", data={"value": "good"}).text
    assert "rejected" in client.post("/check/tmdb_api_key", data={"value": "bad"}).text
    assert client.post("/check/tmdb_api_key", data={"value": ""}).text.strip() == ""
    assert client.post("/check/nope", data={"value": "x"}).status_code == 404
    offline, offline_state = _client(workspace_root / "o", ScriptedChecker(offline=True))
    _enter(offline, offline_state)
    assert "unverified" in offline.post("/check/tmdb_api_key", data={"value": "k"}).text


def test_submit_rejects_missing_required_and_rejected_keys(
    workspace_root: Path, tmp_path: Path
) -> None:
    client, state = _client(workspace_root, ScriptedChecker(bad={"value-tmdb_api_key"}))
    _enter(client, state)
    partial = _full_form(tmp_path / "media")
    partial.pop("web_password")
    html = client.post("/credentials", data=partial).text
    assert "Web UI password is required" in html
    assert "TMDB API key (v3) was rejected" in html
    assert state.run is None


def test_submit_starts_run_and_streams_to_result(workspace_root: Path, tmp_path: Path) -> None:
    client, state = _client(workspace_root)
    _enter(client, state)
    form = _full_form(tmp_path / "media")
    form[extra_field_name("torrent-downloader", "MINIMUM_SEEDERS")] = "42"
    response = client.post("/credentials", data=form)
    assert response.status_code == 303 and response.headers["location"] == "/run"
    assert state.run is not None
    assert state.run.thread is not None
    state.run.thread.join(timeout=10)
    assert state.run.state is RunState.SUCCEEDED, state.run.log.lines
    events = client.get("/events?after=0").text
    assert "medialab-build.sh" in events and "See result" in events
    result = client.get("/result").text
    assert "The stack is up" in result
    written = parse_env_values((workspace_root / "torrent-downloader" / ".env").read_text())
    assert written["TMDB_API_KEY"] == "value-tmdb_api_key"
    assert written["MINIMUM_SEEDERS"] == "42"
    assert (tmp_path / "media" / "_incoming" / "Shows").is_dir()
    for page in (events, result, client.get("/credentials").text):
        assert "value-tmdb_api_key" not in page
        assert "value-web_password" not in page


def test_failed_doctor_shows_stopped_result(workspace_root: Path, tmp_path: Path) -> None:
    client, state = _client(workspace_root)
    state.shell.expect_stream("medialab-doctor.sh", 1)  # type: ignore[attr-defined]
    _enter(client, state)
    client.post("/credentials", data=_full_form(tmp_path / "media"))
    assert state.run is not None and state.run.thread is not None
    state.run.thread.join(timeout=10)
    assert state.run.state is RunState.FAILED
    assert "Install stopped" in client.get("/result").text


def test_prefilled_secret_is_marked_set_and_kept_on_blank(
    workspace_root: Path, tmp_path: Path
) -> None:
    client, state = _client(workspace_root)
    (workspace_root / "torrent-downloader" / ".env").write_text("TMDB_API_KEY=keep-me\n")
    _enter(client, state)
    html = client.get("/credentials").text
    assert "already set" in html and "keep-me" not in html
    form = _full_form(tmp_path / "media")
    form["tmdb_api_key"] = ""
    client.post("/credentials", data=form)
    assert state.run is not None and state.run.thread is not None
    state.run.thread.join(timeout=10)
    written = parse_env_values((workspace_root / "torrent-downloader" / ".env").read_text())
    assert written["TMDB_API_KEY"] == "keep-me"


def test_done_stops_and_idle_stops_only_when_not_running(workspace_root: Path) -> None:
    client, state = _client(workspace_root)
    _enter(client, state)
    assert not should_stop(state)
    assert should_stop(state, now=state.last_activity + IDLE_TIMEOUT_SECONDS)
    state.run = start_run(state.workspace, state.shell, state.checker, {}, in_thread=False)
    state.run.state = RunState.RUNNING
    assert not should_stop(state, now=state.last_activity + IDLE_TIMEOUT_SECONDS)
    state.run.state = RunState.FAILED
    client.post("/done")
    assert should_stop(state)


def test_web_prompter_answers_from_form_and_never_confirms() -> None:
    log = LineLog()
    prompter = WebPrompter({"tmdb_api_key": " k ", extra_field_name("svc", "X"): "7"}, log)
    assert prompter.secret(guide_for("tmdb_api_key").title, has_current=False, help_text="") == "k"
    assert prompter.text("svc: X", default="1", help_text="") == "7"
    assert prompter.text("svc: Y", default="1", help_text="") == "1"
    assert prompter.confirm("Open url?", default=True) is False
    with pytest.raises(CollectError):
        prompter.text("svc: X", default="1", help_text="")
    prompter.note("[bold]Title[/bold] body")
    assert log.lines == ["Title body"]


def test_line_log_buffers_partial_writes() -> None:
    log = LineLog()
    log.write("abc")
    log.write("def\nghi\n")
    assert log.lines == ["abcdef", "ghi"]
    log.flush()
    lines, index = log.since(1)
    assert lines == ["ghi"] and index == 2


@pytest.mark.parametrize("name", REQUIRED_FIELDS)
def test_every_required_field_has_a_guide(name: str) -> None:
    assert guide_for(name).title
