# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-07

### Added

- `wizard` command: a browser-based installer on loopback. Prerequisites page
  with Install buttons, one credentials page with a help popover per field and
  live checks on change, an Advanced section for every template tunable, a
  streamed run page and a doctor result page. Same phases as `setup`, driven
  through the `Prompter` protocol; token-guarded; exits when closed or idle.
  The result page ends with Next steps: every host autostart step with its
  state, an Apply button for the automatable ones (one UAC prompt), and
  instructions with a link for automatic logon and Docker Desktop's switch
  (MickMarch/medialab#135).

## [0.1.3] - 2026-10-07

### Fixed

- The generated qBittorrent WebUI API key now has the shape qBittorrent accepts
  (`qbt_` plus 28 alphanumerics, as `bin/medialab-qbt-provision.sh` makes it).
  The generic 43-character secret was seeded but rejected with 403, so
  provision never saw the WebUI answer.

## [0.1.2] - 2026-10-07

### Fixed

- `setup` and `update` refuse to run compose when the compose project (the
  `name:` in `docker-compose.yml`, or `COMPOSE_PROJECT_NAME`) is already owned
  by another directory. Two clones share one project otherwise, and `up` in
  the second takes over the first's containers and named volumes.

## [0.1.1] - 2026-10-06

### Fixed

- The inline hint after a prompt read like a prefilled value, so Enter sent an
  empty answer. Hints now render as `(e.g. ...)`, and a non-secret prompt with
  no current value is prefilled with the template default so Enter accepts it.

## [0.1.0] - 2026-10-06

### Added

- `update` command: a running / pinned / target table per service and the
  root commits about to be taken; exits early when up to date. Otherwise
  snapshots the root commit and every `.env`, fast-forwards `main` (refusing
  a dirty tree or another branch), updates submodules to their pins, appends
  template keys the live `.env` files lack and flags removed ones, rebuilds,
  recreates, and runs the doctor for the verify window; on failure restores
  the snapshot unless `--no-rollback`. `--to <ref>` targets a root ref,
  `--dry-run` shows the check only (MickMarch/medialab#129).
- Host phase: every step in `docs/host-setup.md` as a check-then-apply pair
  (Jellyfin SYSTEM task, tray autostart off, lock at logon, doctor after
  logon, LAN firewall rule), elevated steps batched into one UAC prompt;
  automatic logon and Docker Desktop's autostart switch are guided manual
  steps rechecked after confirmation. `setup` now runs every phase.
- `setup` now runs Build (`bin/medialab-build.sh`), Provision
  (`bin/medialab-qbt-provision.sh`, `docker compose up -d` with both env
  files, Movies and Shows registered as Jellyfin libraries when missing) and
  Verify (`bin/medialab-doctor.sh`, retried for five minutes). The Host phase
  is a placeholder; `--skip-host` skips it.
- `setup` command through the Generate phase: Preflight (Git, uv, Docker
  Desktop and Jellyfin checked and installed through winget on confirmation,
  download page as fallback; engine, submodules, published ports and a host
  qBittorrent), Collect, then writing every `.env`, the media folders and the
  answers file. `--dry-run`, `--stop-after`, `--yes`. Phases after Generate
  are refused until they land.
- `plan` command: collect answers and show what `setup` would write, writing
  nothing. Express mode asks only the required values still unset; custom
  mode walks every value and every template tunable. Each credential prompt
  shows where to get it, offers to open the console URL, and live-validates
  TMDB, Jellyfin and Discord values with read-only calls.
- Replayable `.medialab-setup/answers.toml` holding non-secret decisions.
- `.env` rendering from each `.env.example`: template order and comments kept,
  values from answers, then the existing file, then the template default;
  keys missing from the template survive under a marker; idempotent.
- `Answers` model with generated inter-service keys and a binding table that
  writes each shared value to every file that needs it, so the key pairs in
  `docs/secrets.md` cannot drift. Atomic writes with a backup under
  `.medialab-setup/backup/`.
- Project scaffold: Typer command tree, shared tooling (ruff, mypy, pre-commit,
  dependabot, workspace CI and release workflows).
