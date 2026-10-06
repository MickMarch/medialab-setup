from pathlib import Path

from pydantic import SecretStr

from medialab_setup.answers import Answers
from medialab_setup.bindings import Binding
from medialab_setup.envfile import parse_env_values
from medialab_setup.generate import collect_existing, render_all, write_all
from medialab_setup.workspace import GLUETUN_TARGET, ROOT_TARGET, Workspace

FIXTURE_BINDINGS = (
    Binding(ROOT_TARGET, "MEDIA_HOST_DIR", "media_host_dir"),
    Binding("svc-a", "API_KEY", "downloader_api_key"),
    Binding("svc-b", "SVC_A_API_KEY", "downloader_api_key"),
    Binding("svc-b", "API_KEY", "orchestrator_api_key"),
    Binding("svc-a", "SHARED_KEY", "tmdb_api_key"),
    Binding("svc-b", "SHARED_KEY", "tmdb_api_key"),
    Binding(GLUETUN_TARGET, "WIREGUARD_PRIVATE_KEY", "wireguard_private_key"),
)
FIXTURE_PAIRS = (
    (("svc-b", "SVC_A_API_KEY"), ("svc-a", "API_KEY")),
    (("svc-b", "SHARED_KEY"), ("svc-a", "SHARED_KEY")),
)


def _values(rendered: dict[str, str], name: str) -> dict[str, str]:
    return parse_env_values(rendered[name])


def test_render_all_covers_every_target(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    answers = Answers(media_host_dir="D:/Media").with_generated()
    rendered = render_all(workspace, answers, bindings=FIXTURE_BINDINGS)
    assert set(rendered) == {ROOT_TARGET, "svc-a", "svc-b", GLUETUN_TARGET}
    assert _values(rendered, ROOT_TARGET)["MEDIA_HOST_DIR"] == "D:/Media"
    assert _values(rendered, ROOT_TARGET)["TZ"] == "America/Toronto"
    assert _values(rendered, "svc-a")["TUNABLE"] == "10"


def test_pairs_never_drift(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    answers = Answers(tmdb_api_key=SecretStr("shared-value")).with_generated()
    rendered = render_all(workspace, answers, bindings=FIXTURE_BINDINGS)
    for (caller, caller_key), (callee, callee_key) in FIXTURE_PAIRS:
        assert _values(rendered, caller)[caller_key] == _values(rendered, callee)[callee_key]
        assert _values(rendered, caller)[caller_key] != ""


def test_unset_asked_value_leaves_template_default(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    rendered = render_all(workspace, Answers().with_generated(), bindings=FIXTURE_BINDINGS)
    assert _values(rendered, ROOT_TARGET)["MEDIA_HOST_DIR"] == "F:/Media"
    assert _values(rendered, GLUETUN_TARGET)["WIREGUARD_PRIVATE_KEY"] == ""


def test_collect_existing_reads_owner_values_into_answers(workspace_root: Path) -> None:
    (workspace_root / "svc-a" / ".env").write_text("API_KEY=existing-a\nSHARED_KEY=\n")
    (workspace_root / ".env").write_text("MEDIA_HOST_DIR=E:/Media\n")
    workspace = Workspace(workspace_root)
    answers = collect_existing(workspace, bindings=FIXTURE_BINDINGS)
    assert answers.downloader_api_key is not None
    assert answers.downloader_api_key.get_secret_value() == "existing-a"
    assert answers.media_host_dir == "E:/Media"
    assert answers.tmdb_api_key is None


def test_existing_owner_value_wins_over_a_drifted_caller(workspace_root: Path) -> None:
    (workspace_root / "svc-a" / ".env").write_text("API_KEY=owner\n")
    (workspace_root / "svc-b" / ".env").write_text("SVC_A_API_KEY=drifted\n")
    workspace = Workspace(workspace_root)
    answers = collect_existing(workspace, bindings=FIXTURE_BINDINGS).with_generated()
    rendered = render_all(workspace, answers, bindings=FIXTURE_BINDINGS)
    assert _values(rendered, "svc-b")["SVC_A_API_KEY"] == "owner"


def test_write_all_is_idempotent_and_backs_up(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    answers = Answers(media_host_dir="D:/Media").with_generated()
    rendered = render_all(workspace, answers, bindings=FIXTURE_BINDINGS)
    first = write_all(workspace, rendered)
    assert len(first) == len(rendered)
    assert (workspace_root / "svc-b" / ".env").exists()
    assert (workspace_root / "gluetun" / "vpn.env").exists()
    assert write_all(workspace, rendered) == []


def test_rendered_output_contains_secret_but_report_does_not(workspace_root: Path) -> None:
    workspace = Workspace(workspace_root)
    answers = Answers(tmdb_api_key=SecretStr("tmdb-secret")).with_generated()
    rendered = render_all(workspace, answers, bindings=FIXTURE_BINDINGS)
    assert "tmdb-secret" not in str(answers.redacted_dump())
    assert "tmdb-secret" in rendered["svc-a"]
