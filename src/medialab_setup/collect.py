"""Phase Collect: build the answers from existing files, the answers file, then prompts.

Precedence: an existing `.env` value wins over the answers file, which wins
over a prompt default. Express asks only required values that are still
unset; custom walks every asked field and every unbound template key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pydantic import SecretStr

from medialab_setup.answers import Answers
from medialab_setup.answers_file import read_answers
from medialab_setup.bindings import ASKED_FIELDS, BINDINGS, REQUIRED_FIELDS, Binding, owner_of
from medialab_setup.checks import CredentialChecker
from medialab_setup.envfile import EnvTemplate, parse_env_values
from medialab_setup.generate import collect_existing
from medialab_setup.guides import guide_for
from medialab_setup.prompts import Prompter, UrlOpener, open_in_browser, render_guide
from medialab_setup.workspace import Workspace


class Mode(str, Enum):
    EXPRESS = "express"
    CUSTOM = "custom"


class Source(str, Enum):
    EXISTING = "existing .env"
    ANSWERS_FILE = "answers file"
    PROMPT = "prompt"
    GENERATED = "generated"
    DEFAULT = "default"


class CollectError(RuntimeError):
    """A value could not be collected without a terminal, or failed validation."""


@dataclass
class Collected:
    answers: Answers
    sources: dict[str, Source] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _secret_set(value: object) -> bool:
    return isinstance(value, SecretStr) and bool(value.get_secret_value())


def _is_set(answers: Answers, name: str) -> bool:
    value = getattr(answers, name)
    return _secret_set(value) if isinstance(value, SecretStr) else value not in (None, "")


def collect(
    workspace: Workspace,
    *,
    mode: Mode,
    prompter: Prompter,
    checker: CredentialChecker,
    answers_file: Path | None = None,
    interactive: bool = True,
    opener: UrlOpener = open_in_browser,
    bindings: tuple[Binding, ...] = BINDINGS,
) -> Collected:
    existing = collect_existing(workspace, bindings)
    sources = {name: Source.EXISTING for name in ASKED_FIELDS if _is_set(existing, name)}
    answers = existing
    if answers_file is not None and answers_file.exists():
        from_file = read_answers(answers_file)
        answers = existing.merged_under(from_file)
        for name in ASKED_FIELDS:
            if name not in sources and _is_set(answers, name):
                sources[name] = Source.ANSWERS_FILE
    collected = Collected(answers=answers, sources=sources)

    to_ask = [
        name
        for name in ASKED_FIELDS
        if mode is Mode.CUSTOM or (name in REQUIRED_FIELDS and not _is_set(answers, name))
    ]
    if to_ask and not interactive:
        raise CollectError(f"missing values with no terminal to ask: {', '.join(to_ask)}")
    for name in to_ask:
        _ask_field(
            collected, name, prompter, checker, opener, _template_default(workspace, name, bindings)
        )

    if mode is Mode.CUSTOM:
        _ask_unbound_keys(workspace, collected, prompter, bindings)

    for name in ASKED_FIELDS:
        if name not in collected.sources:
            collected.sources[name] = Source.DEFAULT
    collected.answers = collected.answers.with_generated()
    return collected


def _template_default(workspace: Workspace, name: str, bindings: tuple[Binding, ...]) -> str:
    """The owning template's default for an asked field, so Enter can accept it."""
    owner = owner_of(name, bindings)
    if owner is None:
        return ""
    target = next((t for t in workspace.env_targets() if t.name == owner.target), None)
    if target is None or not target.example_path.exists():
        return ""
    template = EnvTemplate.from_path(target.example_path)
    return template.default_of(owner.key) if owner.key in template.keys else ""


def _ask_field(
    collected: Collected,
    name: str,
    prompter: Prompter,
    checker: CredentialChecker,
    opener: UrlOpener,
    template_default: str = "",
) -> None:
    guide = guide_for(name)
    prompter.note(render_guide(guide))
    if guide.url and prompter.confirm(f"Open {guide.url} in your browser?", default=False):
        opener(guide.url)
    current = collected.answers.plain_value(name) or ""
    if not current and not guide.secret:
        current = template_default
    while True:
        if guide.secret:
            raw = prompter.secret(
                guide.title, has_current=bool(current), help_text=guide.looks_like
            )
            value = raw or current
        else:
            value = prompter.text(guide.title, default=current, help_text=guide.looks_like)
        if not value:
            if name in REQUIRED_FIELDS:
                prompter.note("A value is required.")
                continue
            break
        if guide.check is None:
            break
        result = checker.run(guide.check, value)
        if result.unverified:
            collected.warnings.append(f"{guide.title}: {result.detail}")
            break
        if result.ok:
            prompter.note(result.detail)
            break
        prompter.note(result.detail)
    if value:
        typed: object = SecretStr(value) if guide.secret else value
        collected.answers = collected.answers.model_copy(update={name: typed})
        collected.sources[name] = Source.PROMPT


def _ask_unbound_keys(
    workspace: Workspace,
    collected: Collected,
    prompter: Prompter,
    bindings: tuple[Binding, ...],
) -> None:
    bound = {(binding.target, binding.key) for binding in bindings}
    extra = {target: dict(keys) for target, keys in collected.answers.extra.items()}
    for target in workspace.env_targets():
        if not target.example_path.exists():
            continue
        template = EnvTemplate.from_path(target.example_path)
        existing = (
            parse_env_values(target.env_path.read_text(encoding="utf-8"))
            if target.env_path.exists()
            else {}
        )
        for entry in template.entries:
            if (target.name, entry.key) in bound:
                continue
            current = extra.get(target.name, {}).get(
                entry.key, existing.get(entry.key, entry.default)
            )
            value = prompter.text(
                f"{target.name}: {entry.key}", default=current, help_text="\n".join(entry.comments)
            )
            if value != entry.default:
                extra.setdefault(target.name, {})[entry.key] = value
            else:
                extra.get(target.name, {}).pop(entry.key, None)
    extra = {target: keys for target, keys in extra.items() if keys}
    collected.answers = collected.answers.model_copy(update={"extra": extra})
