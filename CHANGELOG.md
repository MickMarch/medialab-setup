# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `.env` rendering from each `.env.example`: template order and comments kept,
  values from answers, then the existing file, then the template default;
  keys missing from the template survive under a marker; idempotent.
- `Answers` model with generated inter-service keys and a binding table that
  writes each shared value to every file that needs it, so the key pairs in
  `docs/secrets.md` cannot drift. Atomic writes with a backup under
  `.medialab-setup/backup/`.
- Project scaffold: Typer command tree, shared tooling (ruff, mypy, pre-commit,
  dependabot, workspace CI and release workflows).
