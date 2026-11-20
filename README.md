# medialab-setup

Install and update CLI for the [medialab](https://github.com/MickMarch/medialab)
stack. Runs on the host from a clone of the workspace, before any container
exists. Design: `docs/specs/setup-and-update-cli.md` in the workspace repo.

## Commands

| Command | Purpose |
|---|---|
| `setup` | fresh clone to a verified running stack: preflight, collect, render every `.env`, build, provision, host autostart, doctor |
| `update` | move a running stack to the current pins: check, snapshot, fetch, migrate `.env`, build, recreate, doctor, roll back on failure; once green, remove the retired Discover libraries |
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

## Retired Discover libraries

`setup` (after library registration) and `update` (after a green doctor)
delete the Jellyfin libraries "Discover Movies" and "Discover Shows" when
every path they hold is under the old Discover folder: `DISCOVER_HOST_DIR`
from the root `.env` if still present, otherwise `F:/MedialabDiscover`. A
library with that name and any other path is kept and reported. A Jellyfin
error is a warning, never a failed run. The folder itself is never deleted;
remove it by hand (see `docs/host-setup.md` in the workspace).

## Development

```bash
uv sync --dev
uv run pytest
```
