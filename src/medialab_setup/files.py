"""Atomic file writes with a pre-write backup."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

TEMP_SUFFIX = ".tmp"
ENCODING = "utf-8"


def atomic_write(target: Path, text: str, *, backup_dir: Path) -> bool:
    """Write `text` to `target` via a temp file and rename.

    An existing file with different content is copied to
    `backup_dir/<target parent name>/<target name>` first. Returns False and
    touches nothing when the content is already identical.
    """
    if target.exists():
        if target.read_text(encoding=ENCODING) == text:
            return False
        backup_path = backup_dir / target.parent.name / target.name
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f"{target.name}{TEMP_SUFFIX}")
    try:
        temp_path.write_text(text, encoding=ENCODING, newline="\n")
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
    return True
