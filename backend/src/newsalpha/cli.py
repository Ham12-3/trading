"""`newsalpha` command-line entrypoint. Subcommands are added phase by phase (PRD §14)."""

import typer

from newsalpha import __version__

app = typer.Typer(help="NewsAlpha: LLM signal lab for market announcements.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Research tool only: ingests data, extracts signals, runs backtests. Never trades."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
