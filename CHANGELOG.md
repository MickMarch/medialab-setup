# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
