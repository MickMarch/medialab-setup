"""Command tree. Commands are added by the setup and update work; see the spec."""

import typer

app = typer.Typer(
    name="medialab-setup",
    help="Install and update the medialab stack from a clone of the workspace.",
    no_args_is_help=True,
)
