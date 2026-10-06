"""Parse `.env.example` templates and `.env` files; render one from the other.

The template is the schema: every key it declares is rendered, in its order,
with its comments. Values come from the caller, then the existing file, then
the template default. Keys present in an existing file but not in the template
are kept at the end under a marker so nothing is silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

NOT_IN_TEMPLATE_COMMENT = "# Not in the current .env.example; kept from the previous file."
COMMENT_PREFIX = "#"
ASSIGNMENT_PATTERN = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
QUOTE_CHARS = ('"', "'")
NEEDS_QUOTING = re.compile(r"[\s#]")
QUOTE = '"'
QUOTED_MIN_LENGTH = 2


@dataclass(frozen=True)
class TemplateEntry:
    key: str
    default: str
    comments: tuple[str, ...] = field(default_factory=tuple)
    blank_before: bool = False


@dataclass(frozen=True)
class EnvTemplate:
    """An ordered `.env.example`: leading comments, then entries with their comments."""

    leading: tuple[str, ...]
    entries: tuple[TemplateEntry, ...]
    trailing: tuple[str, ...] = ()

    @classmethod
    def from_path(cls, path: Path) -> EnvTemplate:
        return cls.parse(path.read_text(encoding="utf-8"))

    @classmethod
    def parse(cls, text: str) -> EnvTemplate:
        """Comment blocks before the first key that end in a blank line are the header."""
        leading: list[str] = []
        entries: list[TemplateEntry] = []
        pending_comments: list[str] = []
        blank_before = False
        for number, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped:
                if not entries and pending_comments:
                    if leading:
                        leading.append("")
                    leading.extend(pending_comments)
                    pending_comments = []
                blank_before = True
                continue
            if stripped.startswith(COMMENT_PREFIX):
                pending_comments.append(stripped)
                continue
            match = ASSIGNMENT_PATTERN.match(stripped)
            if match is None:
                raise ValueError(f"line {number} is not a KEY=value assignment: {raw!r}")
            entries.append(
                TemplateEntry(
                    key=match["key"],
                    default=_unquote(match["value"]),
                    comments=tuple(pending_comments),
                    blank_before=blank_before,
                )
            )
            pending_comments = []
            blank_before = False
        return cls(leading=tuple(leading), entries=tuple(entries), trailing=tuple(pending_comments))

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(entry.key for entry in self.entries)

    def default_of(self, key: str) -> str:
        return self._entry(key).default

    def comment_of(self, key: str) -> str:
        return "\n".join(self._entry(key).comments)

    def _entry(self, key: str) -> TemplateEntry:
        for entry in self.entries:
            if entry.key == key:
                return entry
        raise KeyError(key)


def parse_env_values(text: str) -> dict[str, str]:
    """Read KEY=value pairs; the last assignment of a key wins, comments are skipped."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIX):
            continue
        match = ASSIGNMENT_PATTERN.match(stripped)
        if match is None:
            continue
        values[match["key"]] = _unquote(match["value"])
    return values


def render_env(template: EnvTemplate, values: dict[str, str], existing: dict[str, str]) -> str:
    """Render the template with `values`, then `existing`, then the template default."""
    lines: list[str] = []
    if template.leading:
        lines.extend(template.leading)
        lines.append("")
    for index, entry in enumerate(template.entries):
        if entry.blank_before and index > 0:
            lines.append("")
        lines.extend(entry.comments)
        value = values.get(entry.key, existing.get(entry.key, entry.default))
        lines.append(f"{entry.key}={_quote(value)}")
    if template.trailing:
        lines.append("")
        lines.extend(template.trailing)
    extras = [key for key in existing if key not in template.keys]
    if extras:
        lines.append("")
        lines.append(NOT_IN_TEMPLATE_COMMENT)
        lines.extend(f"{key}={_quote(existing[key])}" for key in extras)
    return "\n".join(lines) + "\n"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= QUOTED_MIN_LENGTH and value[0] == value[-1] and value[0] in QUOTE_CHARS:
        return value[1:-1]
    return value


def _quote(value: str) -> str:
    if value and NEEDS_QUOTING.search(value):
        return f"{QUOTE}{value}{QUOTE}"
    return value
