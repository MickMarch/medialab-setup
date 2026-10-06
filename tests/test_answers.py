from pydantic import SecretStr

from medialab_setup.answers import Answers, generate_secret
from medialab_setup.bindings import GENERATED_FIELDS


def test_generate_secret_is_random_and_long() -> None:
    first, second = generate_secret(), generate_secret()
    assert first != second
    assert len(first) >= 32


def test_generated_fields_fill_when_missing() -> None:
    answers = Answers().with_generated()
    for field in GENERATED_FIELDS:
        value = getattr(answers, field)
        assert isinstance(value, SecretStr)
        assert value.get_secret_value()


def test_generated_fields_are_kept_when_present() -> None:
    answers = Answers(orchestrator_api_key=SecretStr("keep-me")).with_generated()
    assert answers.orchestrator_api_key is not None
    assert answers.orchestrator_api_key.get_secret_value() == "keep-me"


def test_secret_fields_do_not_leak_in_repr_or_dump() -> None:
    answers = Answers(tmdb_api_key=SecretStr("tmdb-secret"))
    assert "tmdb-secret" not in repr(answers)
    assert "tmdb-secret" not in str(answers.model_dump())


def test_redacted_dump_drops_secrets_and_keeps_plain_values() -> None:
    answers = Answers(media_host_dir="F:/Media", tmdb_api_key=SecretStr("tmdb-secret"))
    dumped = answers.redacted_dump()
    assert dumped["media_host_dir"] == "F:/Media"
    assert "tmdb-secret" not in str(dumped)
    assert "tmdb_api_key" not in dumped
