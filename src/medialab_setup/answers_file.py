"""The replayable answers file: non-secret decisions only, TOML, under the state dir."""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from medialab_setup.answers import Answers
from medialab_setup.files import atomic_write
from medialab_setup.workspace import STATE_DIR

ANSWERS_FILE = "answers.toml"
HEADER = (
    "# Written by medialab-setup after every run. Non-secret decisions only;\n"
    "# every secret lives in the .env that owns it. Safe to edit, never committed.\n"
)


def answers_path(root: Path) -> Path:
    return root / STATE_DIR / ANSWERS_FILE


def read_answers(path: Path) -> Answers:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return Answers.model_validate(data)


def write_answers(path: Path, answers: Answers, *, backup_dir: Path) -> bool:
    body = tomli_w.dumps(answers.redacted_dump())
    return atomic_write(path, HEADER + body, backup_dir=backup_dir)
