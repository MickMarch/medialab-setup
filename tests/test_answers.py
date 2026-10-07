import re

from pydantic import SecretStr

from medialab_setup.answers import Answers, generate_qbt_api_key, generate_secret
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


QBT_KEY_PATTERN = re.compile(r"^qbt_[A-Za-z0-9]{28}$")


def test_qbt_api_key_matches_the_provision_script_shape() -> None:
    key = generate_qbt_api_key()
    assert QBT_KEY_PATTERN.match(key), key
    assert len(key) == 32


def test_generated_qb_api_key_uses_the_qbt_shape_and_others_do_not() -> None:
    answers = Answers().with_generated()
    assert answers.qb_api_key is not None
    assert QBT_KEY_PATTERN.match(answers.qb_api_key.get_secret_value())
    assert answers.orchestrator_api_key is not None
    assert not QBT_KEY_PATTERN.match(answers.orchestrator_api_key.get_secret_value())
