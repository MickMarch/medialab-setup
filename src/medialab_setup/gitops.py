"""Git over the host boundary: only what update needs, each call one shell command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from medialab_setup.shell import Shell

GIT = "git"
ORIGIN = "origin"
MAIN = "main"
DEFAULT_TARGET = f"{ORIGIN}/{MAIN}"
SUBMODULE_MODE = "160000"
VERSION_PREFIX = "v"


class GitError(RuntimeError):
    """A git command exited non-zero."""


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str


class Git:
    def __init__(self, shell: Shell, root: Path) -> None:
        self.shell = shell
        self.root = root

    def _run(self, *args: str, cwd: Path | None = None) -> str:
        completed = self.shell.run([GIT, "-C", str(cwd or self.root), *args])
        if completed.returncode != 0:
            detail = completed.stderr.strip()
            raise GitError(f"git {' '.join(args)} exited {completed.returncode}: {detail}")
        return completed.stdout.strip()

    def head(self) -> str:
        return self._run("rev-parse", "HEAD")

    def branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD")

    def is_clean(self) -> bool:
        return self._run("status", "--porcelain", "--untracked-files=no") == ""

    def fetch(self) -> None:
        self._run("fetch", "--quiet", ORIGIN)

    def commits_between(self, base: str, target: str) -> list[Commit]:
        output = self._run("log", "--oneline", "--no-decorate", f"{base}..{target}")
        commits: list[Commit] = []
        for line in output.splitlines():
            sha, _, subject = line.partition(" ")
            commits.append(Commit(sha, subject))
        return commits

    def submodule_sha_at(self, ref: str, path: str) -> str | None:
        output = self._run("ls-tree", ref, "--", path)
        if not output:
            return None
        meta, _, _ = output.partition("\t")
        mode, _kind, sha = meta.split()
        return sha if mode == SUBMODULE_MODE else None

    def describe(self, path: str, sha: str | None = None) -> str:
        args = ["describe", "--tags", "--always"]
        if sha:
            args.append(sha)
        return self._run(*args, cwd=self.root / path).removeprefix(VERSION_PREFIX)

    def fetch_submodule(self, path: str) -> None:
        self._run("fetch", "--quiet", ORIGIN, cwd=self.root / path)

    def merge_ff(self, target: str) -> None:
        self._run("merge", "--ff-only", target)

    def checkout_detached(self, sha: str) -> None:
        self._run("checkout", "--quiet", "--detach", sha)

    def submodule_update(self) -> None:
        self._run("submodule", "update", "--init", "--recursive", "--quiet")
