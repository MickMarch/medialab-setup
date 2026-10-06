"""Operator interaction behind one small interface so collection is testable."""

from __future__ import annotations

import sys
import webbrowser
from collections.abc import Callable
from typing import Protocol

import questionary
from rich.console import Console

from medialab_setup.guides import Guide

KEEP_CURRENT_HINT = "Enter keeps the current value"
EXAMPLE_PREFIX = "e.g. "


def hint(help_text: str, *extra: str) -> str:
    """The inline hint after a question, unmistakably an example rather than a default."""
    parts = [f"{EXAMPLE_PREFIX}{help_text}", *extra]
    return f"({'; '.join(parts)})"


class Prompter(Protocol):
    def text(self, message: str, default: str, help_text: str) -> str: ...
    def secret(self, message: str, has_current: bool, help_text: str) -> str: ...
    def confirm(self, message: str, default: bool) -> bool: ...
    def note(self, text: str) -> None: ...


class NonInteractiveError(RuntimeError):
    """A prompt was needed but no terminal is attached."""


class QuestionaryPrompter:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def _require_tty(self) -> None:
        if not sys.stdin.isatty():
            raise NonInteractiveError("a value is missing and stdin is not a terminal")

    def text(self, message: str, default: str, help_text: str) -> str:
        self._require_tty()
        answer = questionary.text(message, default=default, instruction=hint(help_text)).ask()
        return default if answer is None else str(answer)

    def secret(self, message: str, has_current: bool, help_text: str) -> str:
        self._require_tty()
        instruction = hint(help_text, KEEP_CURRENT_HINT) if has_current else hint(help_text)
        answer = questionary.password(message, instruction=instruction).ask()
        return "" if answer is None else str(answer)

    def confirm(self, message: str, default: bool) -> bool:
        self._require_tty()
        answer = questionary.confirm(message, default=default).ask()
        return default if answer is None else bool(answer)

    def note(self, text: str) -> None:
        self.console.print(text)


def render_guide(guide: Guide) -> str:
    lines = [f"[bold]{guide.title}[/bold]"]
    lines.extend(f"  {index}. {step}" for index, step in enumerate(guide.steps, start=1))
    lines.append(f"  Looks like: {guide.looks_like}")
    if guide.url:
        lines.append(f"  Where: {guide.url}")
    return "\n".join(lines)


UrlOpener = Callable[[str], object]


def open_in_browser(url: str) -> object:
    return webbrowser.open(url)
