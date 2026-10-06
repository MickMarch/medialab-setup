"""Command tree. The setup and update commands are added by their own work; see the spec."""

from importlib.metadata import PackageNotFoundError, version

import typer

PACKAGE_NAME = "medialab-setup"
VERSION_UNKNOWN = "unknown"

app = typer.Typer(
    name=PACKAGE_NAME,
    help="Install and update the medialab stack from a clone of the workspace.",
    no_args_is_help=True,
)


def installed_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return VERSION_UNKNOWN


@app.command("version")
def version_cmd() -> None:
    """Print the tool version."""
    typer.echo(installed_version())
