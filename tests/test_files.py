from pathlib import Path

import pytest

from medialab_setup.files import atomic_write


def test_atomic_write_creates_file_and_no_backup_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "svc" / ".env"
    backup_dir = tmp_path / "backup"
    assert atomic_write(target, "A=1\n", backup_dir=backup_dir) is True
    assert target.read_text() == "A=1\n"
    assert not backup_dir.exists()


def test_atomic_write_backs_up_previous_content(tmp_path: Path) -> None:
    target = tmp_path / "svc" / ".env"
    target.parent.mkdir()
    target.write_text("A=old\n")
    backup_dir = tmp_path / "backup"
    atomic_write(target, "A=new\n", backup_dir=backup_dir)
    assert target.read_text() == "A=new\n"
    backups = list(backup_dir.rglob(".env"))
    assert len(backups) == 1
    assert backups[0].read_text() == "A=old\n"
    assert backups[0].parent.name == "svc"


def test_atomic_write_leaves_previous_file_intact_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / ".env"
    target.write_text("A=old\n")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("medialab_setup.files.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write(target, "A=new\n", backup_dir=tmp_path / "backup")
    assert target.read_text() == "A=old\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_skips_when_unchanged(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\n")
    backup_dir = tmp_path / "backup"
    assert atomic_write(target, "A=1\n", backup_dir=backup_dir) is False
    assert not backup_dir.exists()
