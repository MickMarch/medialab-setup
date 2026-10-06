"""Render every `.env` in the workspace from its template and the answers."""

from __future__ import annotations

from pathlib import Path

from medialab_setup.answers import Answers
from medialab_setup.bindings import BINDINGS, Binding, owner_of
from medialab_setup.envfile import EnvTemplate, parse_env_values, render_env
from medialab_setup.files import atomic_write
from medialab_setup.workspace import EnvTarget, Workspace


def _existing_values(target: EnvTarget) -> dict[str, str]:
    if not target.env_path.exists():
        return {}
    return parse_env_values(target.env_path.read_text(encoding="utf-8"))


def collect_existing(workspace: Workspace, bindings: tuple[Binding, ...] = BINDINGS) -> Answers:
    """Build answers from the values the owning `.env` files already hold."""
    existing = {target.name: _existing_values(target) for target in workspace.env_targets()}
    decided: dict[str, str] = {}
    for field in Answers.model_fields:
        owner = owner_of(field, bindings)
        if owner is None:
            continue
        value = existing.get(owner.target, {}).get(owner.key, "")
        if value:
            decided[field] = value
    return Answers.model_validate(decided)


def render_all(
    workspace: Workspace, answers: Answers, bindings: tuple[Binding, ...] = BINDINGS
) -> dict[str, str]:
    """Rendered text per target name. Targets without a template are skipped."""
    rendered: dict[str, str] = {}
    for target in workspace.env_targets():
        if not target.example_path.exists():
            continue
        template = EnvTemplate.from_path(target.example_path)
        values = {
            binding.key: plain
            for binding in bindings
            if binding.target == target.name
            and (plain := answers.plain_value(binding.field)) is not None
        }
        rendered[target.name] = render_env(template, values, existing=_existing_values(target))
    return rendered


def write_all(workspace: Workspace, rendered: dict[str, str]) -> list[Path]:
    """Write every rendered file atomically; returns the paths that changed."""
    by_name = {target.name: target for target in workspace.env_targets()}
    changed: list[Path] = []
    for name, text in rendered.items():
        target = by_name[name]
        if atomic_write(target.env_path, text, backup_dir=workspace.backup_dir):
            changed.append(target.env_path)
    return changed
