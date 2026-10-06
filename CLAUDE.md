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
- Shell, git, Docker and HTTP are reached through small client classes and
  mocked at that boundary in tests.
- Host steps (Task Scheduler, firewall, Docker Desktop settings) print the
  PowerShell they will run and ask once per step; automatic logon is never
  automated.

## Module layout

- `cli.py`: Typer command tree only.
