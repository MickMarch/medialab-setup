from __future__ import annotations

from pathlib import Path

import pytest
from fakes import ScriptedPrompter
from pydantic import SecretStr

from medialab_setup.answers import Answers
from medialab_setup.answers_file import write_answers
from medialab_setup.bindings import ASKED_FIELDS, REQUIRED_FIELDS, Binding
from medialab_setup.checks import CheckResult, CredentialChecker
from medialab_setup.collect import CollectError, Mode, Source, collect
from medialab_setup.guides import Check, guide_for
from medialab_setup.workspace import GLUETUN_TARGET, ROOT_TARGET, Workspace

FIXTURE_BINDINGS = (
    Binding(ROOT_TARGET, "MEDIA_HOST_DIR", "media_host_dir"),
    Binding("svc-a", "SHARED_KEY", "tmdb_api_key"),
    Binding("svc-b", "API_KEY", "orchestrator_api_key"),
    Binding(GLUETUN_TARGET, "WIREGUARD_PRIVATE_KEY", "wireguard_private_key"),
)


class FakeChecker(CredentialChecker):
    def __init__(self, results: dict[str, CheckResult] | None = None) -> None:
        super().__init__()
        self.results = results or {}
        self.calls: list[tuple[Check, str]] = []

    def run(self, check: Check, value: str) -> CheckResult:
        self.calls.append((check, value))
        return self.results.get(value, CheckResult(ok=True, detail="ok"))


def _title(field: str) -> str:
    return guide_for(field).title


def _full_script() -> dict[str, list[str]]:
    return {_title(name): [f"value-{name}"] for name in REQUIRED_FIELDS}


def test_express_asks_only_required_missing_fields(workspace_root: Path) -> None:
    (workspace_root / ".env").write_text("MEDIA_HOST_DIR=E:/Media\n")
    prompter = ScriptedPrompter(_full_script())
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=prompter,
        checker=FakeChecker(),
        bindings=FIXTURE_BINDINGS,
    )
    assert _title("media_host_dir") not in prompter.asked
    assert set(prompter.asked) == {_title(n) for n in REQUIRED_FIELDS if n != "media_host_dir"}
    assert collected.sources["media_host_dir"] is Source.EXISTING
    assert collected.sources["tmdb_api_key"] is Source.PROMPT
    assert collected.sources["timezone"] is Source.DEFAULT
    assert collected.answers.orchestrator_api_key is not None


def test_guide_is_shown_and_url_opened_on_confirm(workspace_root: Path) -> None:
    prompter = ScriptedPrompter(_full_script(), confirms=True)
    opened: list[str] = []
    collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=prompter,
        checker=FakeChecker(),
        opener=opened.append,
        bindings=FIXTURE_BINDINGS,
    )
    assert any(_title("tmdb_api_key") in note for note in prompter.notes)
    assert guide_for("tmdb_api_key").url in opened
    assert guide_for("media_host_dir").url is None


def test_failed_check_reprompts_until_accepted(workspace_root: Path) -> None:
    script = _full_script()
    script[_title("tmdb_api_key")] = ["bad", "good"]
    checker = FakeChecker({"bad": CheckResult(ok=False, detail="TMDB rejected the key")})
    prompter = ScriptedPrompter(script)
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=prompter,
        checker=checker,
        bindings=FIXTURE_BINDINGS,
    )
    assert [value for _, value in checker.calls if _ is Check.TMDB] == ["bad", "good"]
    assert collected.answers.tmdb_api_key is not None
    assert collected.answers.tmdb_api_key.get_secret_value() == "good"
    assert "TMDB rejected the key" in prompter.notes


def test_offline_check_is_a_warning_not_a_block(workspace_root: Path) -> None:
    script = _full_script()
    checker = FakeChecker(
        {f"value-{n}": CheckResult.offline(OSError("down")) for n in REQUIRED_FIELDS}
    )
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=ScriptedPrompter(script),
        checker=checker,
        bindings=FIXTURE_BINDINGS,
    )
    assert collected.warnings
    assert all("unverified" in warning for warning in collected.warnings)


def test_answers_file_fills_gaps_but_existing_env_wins(workspace_root: Path) -> None:
    (workspace_root / ".env").write_text("MEDIA_HOST_DIR=E:/Media\n")
    answers_path = workspace_root / "answers.toml"
    write_answers(
        answers_path,
        Answers(media_host_dir="Z:/Other", timezone="Europe/Paris", discord_guild_id="1234"),
        backup_dir=workspace_root / "bk",
    )
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=ScriptedPrompter(_full_script()),
        checker=FakeChecker(),
        answers_file=answers_path,
        bindings=FIXTURE_BINDINGS,
    )
    assert collected.answers.media_host_dir == "E:/Media"
    assert collected.sources["media_host_dir"] is Source.EXISTING
    assert collected.answers.timezone == "Europe/Paris"
    assert collected.sources["timezone"] is Source.ANSWERS_FILE
    assert collected.sources["discord_guild_id"] is Source.ANSWERS_FILE


def test_non_interactive_with_missing_values_fails(workspace_root: Path) -> None:
    with pytest.raises(CollectError, match="tmdb_api_key"):
        collect(
            Workspace(workspace_root),
            mode=Mode.EXPRESS,
            prompter=ScriptedPrompter({}),
            checker=FakeChecker(),
            interactive=False,
            bindings=FIXTURE_BINDINGS,
        )


def test_required_field_rejects_empty_answer(workspace_root: Path) -> None:
    script = _full_script()
    script[_title("web_password")] = ["", "finally"]
    prompter = ScriptedPrompter(script)
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=prompter,
        checker=FakeChecker(),
        bindings=FIXTURE_BINDINGS,
    )
    assert collected.answers.web_password is not None
    assert collected.answers.web_password.get_secret_value() == "finally"
    assert "A value is required." in prompter.notes


def test_custom_asks_every_field_and_unbound_template_keys(workspace_root: Path) -> None:
    script = _full_script()
    script["svc-a: TUNABLE"] = ["42"]
    prompter = ScriptedPrompter(script)
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.CUSTOM,
        prompter=prompter,
        checker=FakeChecker(),
        bindings=FIXTURE_BINDINGS,
    )
    for name in ASKED_FIELDS:
        assert _title(name) in prompter.asked
    assert "svc-a: TUNABLE" in prompter.asked
    assert "svc-a: API_KEY" in prompter.asked
    assert "root: TZ" in prompter.asked
    assert collected.answers.extra == {"svc-a": {"TUNABLE": "42"}}


def test_custom_keeps_current_secret_on_empty_answer(workspace_root: Path) -> None:
    (workspace_root / "svc-a" / ".env").write_text("SHARED_KEY=keep\n")
    script = _full_script()
    script[_title("tmdb_api_key")] = [""]
    collected = collect(
        Workspace(workspace_root),
        mode=Mode.CUSTOM,
        prompter=ScriptedPrompter(script),
        checker=FakeChecker(),
        bindings=FIXTURE_BINDINGS,
    )
    assert collected.answers.tmdb_api_key is not None
    assert collected.answers.tmdb_api_key.get_secret_value() == "keep"


def test_secret_values_never_appear_in_notes(workspace_root: Path) -> None:
    prompter = ScriptedPrompter(_full_script())
    collect(
        Workspace(workspace_root),
        mode=Mode.EXPRESS,
        prompter=prompter,
        checker=FakeChecker(),
        bindings=FIXTURE_BINDINGS,
    )
    joined = "\n".join(prompter.notes)
    for name in REQUIRED_FIELDS:
        if guide_for(name).secret:
            assert f"value-{name}" not in joined


def test_fake_secret_type_roundtrip() -> None:
    assert SecretStr("x").get_secret_value() == "x"
