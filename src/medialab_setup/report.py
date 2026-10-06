"""Rich tables for what was collected and what would be written. Never a secret value."""

from __future__ import annotations

from rich.table import Table

from medialab_setup.answers import Answers
from medialab_setup.bindings import ASKED_FIELDS, GENERATED_FIELDS
from medialab_setup.collect import Collected, Source
from medialab_setup.envfile import parse_env_values
from medialab_setup.guides import guide_for
from medialab_setup.workspace import Workspace

SET_MARK = "set"
MISSING_MARK = "missing"
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_UNCHANGED = "unchanged"


def _display_value(answers: Answers, name: str, secret: bool) -> str:
    value = answers.plain_value(name)
    if not value:
        return MISSING_MARK
    return SET_MARK if secret else value


def answers_table(collected: Collected) -> Table:
    table = Table(title="Answers")
    table.add_column("Value")
    table.add_column("Source")
    table.add_column("State")
    for name in ASKED_FIELDS:
        guide = guide_for(name)
        table.add_row(
            guide.title,
            collected.sources.get(name, Source.DEFAULT).value,
            _display_value(collected.answers, name, guide.secret),
        )
    for name in GENERATED_FIELDS:
        table.add_row(name, Source.GENERATED.value, _display_value(collected.answers, name, True))
    return table


def files_table(workspace: Workspace, rendered: dict[str, str]) -> Table:
    table = Table(title="Files")
    table.add_column("File")
    table.add_column("Action")
    table.add_column("Keys changing")
    for target in workspace.env_targets():
        if target.name not in rendered:
            continue
        new_text = rendered[target.name]
        if not target.env_path.exists():
            action, changed = ACTION_CREATE, list(parse_env_values(new_text))
        else:
            old_text = target.env_path.read_text(encoding="utf-8")
            if old_text == new_text:
                action, changed = ACTION_UNCHANGED, []
            else:
                old_values, new_values = parse_env_values(old_text), parse_env_values(new_text)
                changed = [
                    key
                    for key in dict.fromkeys([*old_values, *new_values])
                    if old_values.get(key) != new_values.get(key)
                ]
                action = ACTION_UPDATE
        relative = target.env_path.relative_to(workspace.root).as_posix()
        table.add_row(relative, action, ", ".join(changed))
    return table
