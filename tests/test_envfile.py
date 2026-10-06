from pathlib import Path

import pytest

from medialab_setup.envfile import (
    NOT_IN_TEMPLATE_COMMENT,
    EnvTemplate,
    parse_env_values,
    render_env,
)

TEMPLATE = """# Leading comment.

# Explains KEY_A.
KEY_A=default-a
KEY_B=
KEY_C="quoted"
"""


def test_template_parse_keeps_order_comments_and_defaults() -> None:
    template = EnvTemplate.parse(TEMPLATE)
    assert [entry.key for entry in template.entries] == ["KEY_A", "KEY_B", "KEY_C"]
    assert template.default_of("KEY_A") == "default-a"
    assert template.default_of("KEY_B") == ""
    assert template.default_of("KEY_C") == "quoted"
    assert template.comment_of("KEY_A") == "# Explains KEY_A."


def test_parse_env_values_reads_last_assignment_and_strips_quotes() -> None:
    values = parse_env_values('KEY_A=1\nKEY_A="2"\n# KEY_B=ignored\nKEY_C=a=b\n')
    assert values == {"KEY_A": "2", "KEY_C": "a=b"}


def test_render_every_template_key_in_order_with_comments() -> None:
    template = EnvTemplate.parse(TEMPLATE)
    out = render_env(template, {"KEY_B": "set-b"}, existing={})
    assert (
        out
        == """# Leading comment.

# Explains KEY_A.
KEY_A=default-a
KEY_B=set-b
KEY_C=quoted
"""
    )


def test_render_prefers_value_over_existing_over_default() -> None:
    template = EnvTemplate.parse(TEMPLATE)
    out = render_env(
        template, {"KEY_A": "from-answers"}, existing={"KEY_A": "old", "KEY_B": "kept"}
    )
    values = parse_env_values(out)
    assert values["KEY_A"] == "from-answers"
    assert values["KEY_B"] == "kept"
    assert values["KEY_C"] == "quoted"


def test_render_keeps_extra_existing_keys_under_marker() -> None:
    template = EnvTemplate.parse(TEMPLATE)
    out = render_env(template, {}, existing={"LEGACY": "1"})
    assert out.rstrip().endswith(f"{NOT_IN_TEMPLATE_COMMENT}\nLEGACY=1")


def test_render_is_idempotent() -> None:
    template = EnvTemplate.parse(TEMPLATE)
    first = render_env(template, {"KEY_B": "x"}, existing={"LEGACY": "1"})
    second = render_env(template, {}, existing=parse_env_values(first))
    assert first == second


def test_render_quotes_values_with_spaces_or_hash() -> None:
    template = EnvTemplate.parse("KEY=\n")
    out = render_env(template, {"KEY": "a b #c"}, existing={})
    assert out == 'KEY="a b #c"\n'
    assert parse_env_values(out) == {"KEY": "a b #c"}


def test_template_parse_rejects_malformed_line() -> None:
    with pytest.raises(ValueError, match="line 1"):
        EnvTemplate.parse("not an assignment\n")


def test_template_from_path(tmp_path: Path) -> None:
    path = tmp_path / ".env.example"
    path.write_text(TEMPLATE)
    assert EnvTemplate.from_path(path).default_of("KEY_A") == "default-a"


def test_trailing_comments_survive_render() -> None:
    template = EnvTemplate.parse("KEY=\n# --- alternative block\n# OTHER=1\n")
    assert template.trailing == ("# --- alternative block", "# OTHER=1")
    out = render_env(template, {}, existing={})
    assert out.endswith("# --- alternative block\n# OTHER=1\n")
    assert parse_env_values(out) == {"KEY": ""}
