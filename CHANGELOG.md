# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-11-20

### Added

- `remove_discover_libraries` deletes the retired "Discover Movies" and
  "Discover Shows" Jellyfin libraries whose every path is under the old
  `DISCOVER_HOST_DIR` (default `F:/MedialabDiscover`); a same-name library
  with any other path is kept and reported. `update` runs it after a green
  doctor and on every non-dry-run up-to-date run, so a teardown that warned is
  retried; `setup` runs it after library registration. A Jellyfin error, an
  unexpected response body or a drive-only folder is a warning that names each
  library left behind and points to the Jellyfin dashboard
  (MickMarch/medialab#168).
- `update` migration drops keys retired from a service template instead of
  carrying them over: `DISCOVER_MOUNT_PATH` from medialab-jellyfin and
  `DISCOVER_REFRESH_SECONDS`, `DISCOVER_POLL_SECONDS`,
  `DISCOVER_RECOMMENDATIONS_PER_TITLE`, `JELLYFIN_REQUEST_USERS`,
  `JELLYFIN_REQUEST_RETRY_HOURS`, `JELLYFIN_REQUEST_RESOLUTION` and
  `JELLYFIN_WEBHOOK_SECRET` from medialab-orchestrator. The root
  `DISCOVER_HOST_DIR` is kept for the teardown (MickMarch/medialab#168).

### Removed

- Setup no longer creates the Discover folders or the "Discover Movies" and
  "Discover Shows" libraries; `ensure_discover_libraries`, `discover_folders`
  and the `DISCOVER_HOST_DIR` binding are gone (MickMarch/medialab#168).

## [0.4.0] - 2026-11-03

### Added

- Setup creates the `DISCOVER_HOST_DIR` folders (Movies, Shows, `_clip`) and the
  "Discover Movies" and "Discover Shows" Jellyfin libraries, skipping any
  already present by name or path (MickMarch/medialab#156).

### Changed

- medialab-contracts pin v1.3.0 -> v1.6.1.

## [0.3.2] - 2026-11-03

### Security

- certifi 2026.10.23 (pip-audit).

## [0.3.1] - 2026-10-07

### Fixed

- `update` now treats a service running behind its pin as work to do, so
  pins bumped without a rebuild are deployed instead of reported as up to
  date. Migration no longer blocks on a new key that is bound to an optional
  answer and defaults to empty (the Discord notify webhook).

## [0.3.0] - 2026-10-07

### Added

- `check-credentials`: reads the gateway's credential health and raises a
  Windows toast per invalid key, once a day, with a button that opens the
  wizard on that field. A new host step registers it as a scheduled task
  every thirty minutes.
- `wizard --fix <name>` (and `setup.cmd --fix <name>`): the credentials page
  with only that field, the new value checked against its service, written
  to its `.env`, the owning container recreated, and the gateway polled until
  the key reads ok. No build, no provision (MickMarch/medialab#136).

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
