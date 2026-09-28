"""`newsalpha` command-line entrypoint. Subcommands are added phase by phase (PRD §14)."""

import logging
from datetime import date, datetime
from typing import Annotated

import typer
from sqlalchemy.orm import Session

from newsalpha import __version__
from newsalpha.core.config import ConfigError, get_settings
from newsalpha.core.time_rules import EASTERN
from newsalpha.core.universe import load_universe
from newsalpha.db.session import get_engine

app = typer.Typer(help="NewsAlpha: LLM signal lab for market announcements.", no_args_is_help=True)
ingest_app = typer.Typer(help="Pull announcements and prices into Postgres.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")

SinceOption = Annotated[
    str, typer.Option("--since", help="Start date, YYYY-MM-DD (inclusive).", show_default=False)
]


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    """Research tool only: ingests data, extracts signals, runs backtests. Never trades."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"expected YYYY-MM-DD, got {value!r}") from exc


def _print_failures(failures: dict[str, str]) -> None:
    for key, err in sorted(failures.items()):
        typer.secho(f"  FAILED {key}: {err}", fg=typer.colors.RED, err=True)


@ingest_app.command("announcements")
def ingest_announcements_cmd(since: SinceOption) -> None:
    """Fetch 8-K Item 2.02 earnings releases (Exhibit 99.1) from SEC EDGAR."""
    from newsalpha.ingest.announcements import (
        AnnouncementIngestReport,
        ingest_announcements,
        upsert_companies,
    )
    from newsalpha.sources.edgar import EdgarClient, EdgarSource

    start = _parse_date(since)
    settings = get_settings()
    try:
        user_agent = settings.sec_user_agent()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    universe = load_universe(settings.universe_path)
    client = EdgarClient(user_agent, settings.sec_max_requests_per_second)
    source = EdgarSource(client)
    report = AnnouncementIngestReport()
    try:
        with Session(get_engine()) as session:
            companies, mapping_errors = upsert_companies(session, universe, source.ticker_map())
            report.failures.update(mapping_errors)
            ingest_announcements(session, source, companies, start, settings.data_dir, report)
    finally:
        client.close()

    typer.echo(
        f"companies ok: {report.companies}/{len(universe.companies)}  "
        f"filings found: {report.filings_found}  inserted: {report.inserted}  "
        f"already stored: {report.already_stored}  no EX-99 exhibit: {report.no_exhibit}  "
        f"failures: {len(report.failures)}"
    )
    if report.failures:
        _print_failures(report.failures)
        raise typer.Exit(1)


@ingest_app.command("prices")
def ingest_prices_cmd(
    since: SinceOption,
    until: Annotated[
        str | None, typer.Option("--until", help="End date (inclusive); default today.")
    ] = None,
) -> None:
    """Fetch adjusted daily bars for the universe and the benchmark."""
    from newsalpha.ingest.prices import ingest_prices
    from newsalpha.sources.yahoo import YahooPriceSource

    start = _parse_date(since)
    end = _parse_date(until) if until else datetime.now(EASTERN).date()
    universe = load_universe(get_settings().universe_path)
    symbols = [universe.benchmark, *universe.tickers]
    with Session(get_engine()) as session:
        report = ingest_prices(session, YahooPriceSource(), symbols, start, end)

    typer.echo(
        f"symbols ok: {report.symbols_ok}/{len(symbols)}  rows upserted: {report.rows_upserted}  "
        f"failures: {len(report.failures)}"
    )
    if report.failures:
        _print_failures(report.failures)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
