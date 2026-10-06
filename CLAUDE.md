# CLAUDE.md - medialab-setup

Workspace rules, conventions, standards and workflow live in the root
[`medialab/CLAUDE.md`](../CLAUDE.md); it is the authority when anything here
disagrees. This file holds only what is specific to this code.

## Purpose

The install and update CLI. Spec: `docs/specs/setup-and-update-cli.md` in
the workspace. Not a service: no container, no compose entry, no `.env` of
its own. It drives the existing `bin/` scripts and writes the service `.env`
files; it never imports a service package.

## Rules specific to this repo

- Each service's `.env.example` is the schema. Render from it; never keep a
  parallel list of variables here.
- Shared values are generated or derived once and written everywhere; the
  key-pair table in `docs/secrets.md` is encoded as a test fixture.
- No secret is ever printed, logged, or written to `answers.toml`.
- Every write is atomic with a backup under `.medialab-setup/backup/`.
- Shell, git, Docker and HTTP are reached through `Shell` and `CredentialChecker`
  and faked at that boundary in tests (`tests/fakes.py`).
- Media folder names come from `medialab-contracts`, never literals here.
- Host steps (Task Scheduler, firewall, Docker Desktop settings) print the
  PowerShell they will run and ask once per step; automatic logon is never
  automated.

## Module layout

- `cli.py`: Typer command tree only.
- `workspace.py`: `.env` targets from `docker-compose.yml` build services plus root and gluetun; state and backup dirs.
- `envfile.py`: parse `.env.example` (order, comments, defaults) and `.env`; render one from the other.
- `files.py`: atomic write with pre-write backup.
- `answers.py`: the `Answers` model (asked, generated), secret-safe dumps.
- `bindings.py`: (target, key) to answers-field table; owners first; `KEY_PAIRS` from `docs/secrets.md`.
- `generate.py`: collect existing values, render every target, write all.
- `guides.py`: per asked credential, the console URL, click path, shape and which live check applies.
- `checks.py`: `CredentialChecker`, read-only TMDB/Jellyfin/Discord calls; offline is a warning.
- `prompts.py`: `Prompter` protocol, questionary implementation, guide rendering, browser opener.
- `answers_file.py`: `.medialab-setup/answers.toml` read/write, non-secret only.
- `collect.py`: phase Collect; precedence existing > answers file > prompt; express/custom.
- `report.py`: Rich tables for answers and files; values shown only for non-secrets.
- `shell.py`: `Shell`, the host boundary (processes, ports, disk, local HTTP); `FakeShell` in tests.
- `preflight.py`: phase Preflight; prerequisite table with winget ids and download URLs; engine, submodule, port and host-qBittorrent rows.
- `setup_flow.py`: phase order, `SetupOptions`, `SetupContext`, the runners; `IMPLEMENTED_THROUGH` gates `--stop-after`.
