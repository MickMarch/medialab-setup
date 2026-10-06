from typer.testing import CliRunner

from medialab_setup.cli import app

runner = CliRunner()


def test_help_lists_tool_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "medialab-setup" in result.output
