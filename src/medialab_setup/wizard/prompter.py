"""The Prompter the wizard hands to the CLI phases: answers come from the submitted form."""

from __future__ import annotations

import re

from medialab_setup.collect import CollectError
from medialab_setup.guides import GUIDES, Guide, guide_for
from medialab_setup.wizard.log import LineLog

EXTRA_FIELD_PREFIX = "extra__"
EXTRA_FIELD_SEPARATOR = "__"


def extra_field_name(target: str, key: str) -> str:
    """Form field name for an unbound template key, as the Advanced section renders it."""
    return f"{EXTRA_FIELD_PREFIX}{target}{EXTRA_FIELD_SEPARATOR}{key}"


class WebPrompter:
    """Text and secret prompts resolve against the form; confirms never open a browser."""

    def __init__(self, form: dict[str, str], log: LineLog) -> None:
        self.form = form
        self.log = log
        self._title_to_field = {guide.title: guide.field for guide in _all_guides()}
        self._asked: set[str] = set()

    def _once(self, message: str) -> None:
        """A second ask means the first answer was rejected; a form cannot answer differently."""
        if message in self._asked:
            raise CollectError(f"{message}: the submitted value was empty or rejected")
        self._asked.add(message)

    def _lookup(self, message: str, default: str) -> str:
        field = self._title_to_field.get(message)
        if field is not None:
            return self.form.get(field, "").strip() or default
        target, _, key = message.partition(": ")
        if key:
            return self.form.get(extra_field_name(target, key), "").strip() or default
        return default

    def text(self, message: str, default: str, help_text: str) -> str:
        self._once(message)
        return self._lookup(message, default)

    def secret(self, message: str, has_current: bool, help_text: str) -> str:
        self._once(message)
        return self._lookup(message, "")

    def confirm(self, message: str, default: bool) -> bool:
        return False

    def note(self, text: str) -> None:
        self.log.append(_strip_markup(text))


def _all_guides() -> list[Guide]:
    return list(GUIDES)


def _strip_markup(text: str) -> str:
    """Rich markup tags the CLI uses in notes have no place in a plain log."""
    return re.sub(r"\[/?[a-z ]+\]", "", text)


__all__ = ["WebPrompter", "extra_field_name", "guide_for"]
