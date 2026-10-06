from pathlib import Path

import pytest
from fakes import FakeShell

from medialab_setup.gitops import Git, GitError


def test_describe_strips_the_v_prefix(tmp_path: Path) -> None:
    shell = FakeShell()
    shell.expect("describe", stdout="v1.2.3\n")
    assert Git(shell, tmp_path).describe("svc") == "1.2.3"
    assert shell.runs[-1][:3] == ["git", "-C", str(tmp_path / "svc")]


def test_submodule_sha_only_for_gitlinks(tmp_path: Path) -> None:
    shell = FakeShell()
    shell.expect("ls-tree origin/main -- svc", stdout="160000 commit abc\tsvc\n")
    shell.expect("ls-tree origin/main -- docs", stdout="040000 tree def\tdocs\n")
    shell.expect("ls-tree origin/main -- gone", stdout="")
    git = Git(shell, tmp_path)
    assert git.submodule_sha_at("origin/main", "svc") == "abc"
    assert git.submodule_sha_at("origin/main", "docs") is None
    assert git.submodule_sha_at("origin/main", "gone") is None


def test_commits_between_parses_oneline(tmp_path: Path) -> None:
    shell = FakeShell()
    shell.expect("log --oneline", stdout="abc feat: one\ndef fix: two\n")
    commits = Git(shell, tmp_path).commits_between("HEAD", "origin/main")
    assert [(c.sha, c.subject) for c in commits] == [("abc", "feat: one"), ("def", "fix: two")]


def test_non_zero_exit_raises(tmp_path: Path) -> None:
    shell = FakeShell()
    shell.expect("merge", returncode=128)
    with pytest.raises(GitError, match="merge"):
        Git(shell, tmp_path).merge_ff("origin/main")
