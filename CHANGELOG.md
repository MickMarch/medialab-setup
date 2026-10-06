# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
