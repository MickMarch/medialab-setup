# medialab-setup

Install and update CLI for the [medialab](https://github.com/MickMarch/medialab)
stack. Runs on the host from a clone of the workspace, before any container
exists. Design: `docs/specs/setup-and-update-cli.md` in the workspace repo.

## Commands

| Command | Purpose |
|---|---|
| `setup` | fresh clone to a verified running stack: preflight, collect, render every `.env`, build, provision, host autostart, doctor |
| `update` | move a running stack to the current pins: check, snapshot, fetch, migrate `.env`, build, recreate, doctor, roll back on failure |
| `wizard` | the same install in a browser page on loopback; `setup.cmd` at the workspace root launches it |
| `wizard --fix <name>` | replace one credential the stack reports invalid: one field, check, write, recreate its container, verify |
| `check-credentials` | toast each invalid credential once a day; registered as a scheduled task by the host step |
| `plan` | collect and show what `setup` would write, writing nothing |

## Running

From the workspace root:

```bash
bin/medialab-setup.sh --help
```

Or directly:

```bash
uv run --project medialab-setup medialab-setup --help
```

## Configuration

The tool reads no `.env` of its own. It reads each service's `.env.example`
as the schema and writes that service's `.env`; secrets live only in the
`.env` that owns them. Non-secret answers are replayed from
`.medialab-setup/answers.toml` at the workspace root (gitignored).

## Development

```bash
uv sync --dev
uv run pytest
```
