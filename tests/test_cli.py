from typer.testing import CliRunner

from medialab_setup.cli import VERSION_UNKNOWN, app, installed_version

runner = CliRunner()


def test_help_lists_tool_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "medialab-setup" in result.output


def test_version_prints_installed_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == installed_version()
    assert result.output.strip() != ""


def test_unknown_version_is_a_named_constant() -> None:
    assert VERSION_UNKNOWN == "unknown"
