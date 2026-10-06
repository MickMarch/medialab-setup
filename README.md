# medialab-setup

Install and update CLI for the [medialab](https://github.com/MickMarch/medialab)
stack. Runs on the host from a clone of the workspace, before any container
exists. Design: `docs/specs/setup-and-update-cli.md` in the workspace repo.

## Commands

| Command | Purpose |
|---|---|
| `setup` | fresh clone to a verified running stack: preflight, collect, render every `.env`, build, provision, host autostart, doctor |
| `update` | move a running stack to the current pins: check, snapshot, fetch, migrate `.env`, build, recreate, doctor, roll back on failure |
| `plan` | `setup --dry-run` |

`plan` and `setup` are available; `setup` runs every phase except Host, which is a placeholder until it lands. `update` follows.

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
