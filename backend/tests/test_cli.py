"""CLI entrypoint."""

from typer.testing import CliRunner

from newsalpha import __version__
from newsalpha.cli import app


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
