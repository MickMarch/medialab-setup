from pathlib import Path

from pydantic import SecretStr

from medialab_setup.answers import Answers
from medialab_setup.answers_file import answers_path, read_answers, write_answers
from medialab_setup.workspace import STATE_DIR


def test_roundtrip_keeps_plain_values_and_drops_secrets(tmp_path: Path) -> None:
    path = tmp_path / "answers.toml"
    answers = Answers(
        media_host_dir="F:/Media",
        timezone="America/Toronto",
        tmdb_api_key=SecretStr("tmdb-secret"),
        extra={"svc-a": {"TUNABLE": "42"}},
    )
    write_answers(path, answers, backup_dir=tmp_path / "bk")
    text = path.read_text()
    assert "tmdb-secret" not in text
    assert "tmdb_api_key" not in text
    loaded = read_answers(path)
    assert loaded.media_host_dir == "F:/Media"
    assert loaded.timezone == "America/Toronto"
    assert loaded.tmdb_api_key is None
    assert loaded.extra == {"svc-a": {"TUNABLE": "42"}}


def test_answers_path_is_under_state_dir(tmp_path: Path) -> None:
    assert answers_path(tmp_path).parent == tmp_path / STATE_DIR
