"""`newsalpha` command-line entrypoint. Subcommands are added phase by phase (PRD §14)."""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import click
import typer
from sqlalchemy.orm import Session

from newsalpha import __version__
from newsalpha.core.config import ConfigError, get_settings
from newsalpha.core.time_rules import EASTERN
from newsalpha.core.universe import load_universe
from newsalpha.db.session import get_engine

if TYPE_CHECKING:
    from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
    from newsalpha.extraction.prompts import Prompt
    from newsalpha.extraction.providers import LLMProvider

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
            predecessors = {m.ticker: m.predecessor_ciks for m in universe.companies}
            ingest_announcements(
                session, source, companies, start, settings.data_dir, report, predecessors
            )
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
        lookup = {m.ticker: m.lookup_ticker for m in universe.companies if m.current_ticker}
        report = ingest_prices(session, YahooPriceSource(), symbols, start, end, lookup)

    typer.echo(
        f"symbols ok: {report.symbols_ok}/{len(symbols)}  rows upserted: {report.rows_upserted}  "
        f"failures: {len(report.failures)}"
    )
    if report.failures:
        _print_failures(report.failures)
        raise typer.Exit(1)


@dataclass(frozen=True)
class _LLMSetup:
    model: str
    price: "ModelPrice"
    prompt: "Prompt"
    provider: "LLMProvider"
    extraction: "ExtractionSettings"


def _llm_setup(model: str | None, prompt_version: str, role: str = "bulk") -> _LLMSetup:
    """Resolve model, price, prompt and provider; exit with a clear message on bad config."""
    from newsalpha.extraction.models_config import load_models_config
    from newsalpha.extraction.prompts import load_prompt
    from newsalpha.extraction.providers import ProviderError, make_provider

    settings = get_settings()
    cfg = load_models_config()
    model = model or cfg.defaults[role]
    try:
        price = cfg.price(model)
        prompt = load_prompt(prompt_version)
        provider = make_provider(
            price.provider,
            {"openai": settings.openai_api_key, "anthropic": settings.anthropic_api_key},
        )
    except (KeyError, ValueError, FileNotFoundError, ProviderError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    return _LLMSetup(model, price, prompt, provider, cfg.extraction)


ModelOption = Annotated[
    str | None, typer.Option("--model", help="Default: from config/models.yaml defaults.")
]
PromptVersionOption = Annotated[str, typer.Option("--prompt-version")]


@app.command()
def extract(
    model: ModelOption = None,
    prompt_version: PromptVersionOption = "v1",
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    retry_failed: Annotated[bool, typer.Option("--retry-failed")] = False,
) -> None:
    """Extract LLM signals for announcements that do not have them yet."""
    from sqlalchemy import func, select

    from newsalpha.core.stats import percentile
    from newsalpha.db.models import Signal
    from newsalpha.extraction.runner import PromptChangedError, run_extraction

    llm = _llm_setup(model, prompt_version)
    with Session(get_engine()) as session:
        try:
            report = run_extraction(
                session=session,
                provider=llm.provider,
                model=llm.model,
                prompt=llm.prompt,
                price=llm.price,
                settings=llm.extraction,
                data_dir=get_settings().data_dir,
                limit=limit,
                retry_failed=retry_failed,
            )
        except PromptChangedError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        totals = session.execute(
            select(Signal.status, func.count(), func.sum(Signal.cost_usd))
            .where(Signal.model == llm.model, Signal.prompt_version == llm.prompt.version)
            .group_by(Signal.status)
        ).all()

    paid = len(report.latencies_ms)
    typer.echo(f"model {llm.model}, prompt {llm.prompt.version}")
    typer.echo(
        f"this run: documents {report.documents}  ok {report.ok}  failed {report.failed}  "
        f"failure rate {report.failure_rate:.1%}  cache hits {report.cache_hits}  "
        f"truncated {report.truncated}"
    )
    typer.echo(
        f"cost ${report.cost_usd:.4f}"
        + (f" (${report.cost_usd / paid:.5f}/doc)" if paid else "")
        + f"  latency p50 {percentile(report.latencies_ms, 50) / 1000:.1f}s"
        f"  p95 {percentile(report.latencies_ms, 95) / 1000:.1f}s"
    )
    summary = ", ".join(f"{status} {n} (${cost or 0:.4f})" for status, n, cost in totals)
    typer.echo(f"all runs of {llm.model}/{llm.prompt.version}: {summary or 'none'}")
    if report.failed:
        raise typer.Exit(1)


# ----------------------------------------------------------------------------- eval

eval_app = typer.Typer(help="Gold labelling and model evaluation.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")
GoldOption = Annotated[Path, typer.Option("--gold", help="Gold labels file (JSONL).")]
DEFAULT_GOLD = Path("../eval/gold/gold.jsonl")


def _print_metrics(metrics: dict[str, Any]) -> None:
    for name, f in metrics["fields"].items():
        typer.echo(f"  {name:<24} accuracy {f['accuracy']:.1%}")
    typer.echo(f"  {'mean accuracy':<24} {metrics['mean_accuracy']:.1%}")
    mae = metrics["management_tone_mae"]
    typer.echo(f"  {'management_tone MAE':<24} {mae:.3f}" if mae is not None else "  tone MAE n/a")
    typer.echo(f"  {'schema failure rate':<24} {metrics['schema_failure_rate']:.1%}")
    cost = metrics["mean_cost_per_doc_usd"]
    if cost is not None:
        typer.echo(
            f"  {'cost per doc':<24} ${cost:.5f}   latency p50 "
            f"{metrics['latency_p50_ms'] / 1000:.1f}s  p95 {metrics['latency_p95_ms'] / 1000:.1f}s"
        )


@eval_app.command("label")
def eval_label(
    n: Annotated[int, typer.Option("--n", min=1, help="Documents to label this session.")] = 10,
    gold_path: GoldOption = DEFAULT_GOLD,
    labeller: Annotated[str | None, typer.Option("--labeller")] = None,
    preview_chars: Annotated[int, typer.Option("--preview-chars")] = 6000,
) -> None:
    """Label announcements by hand. Answers are saved after every document."""
    from sqlalchemy import select

    from newsalpha.db.models import Announcement, Company
    from newsalpha.eval.gold import GoldRecord, append_gold, load_gold
    from newsalpha.eval.labelling import (
        QuitLabelling,
        SkipDocument,
        ask_labels,
        labelling_order,
        load_skipped,
        record_skip,
    )

    settings = get_settings()
    who = labeller or settings.sec_user_agent_name or "owner"
    done = {g.source_id for g in load_gold(gold_path)} | load_skipped()
    with Session(get_engine()) as session:
        rows = session.execute(
            select(Announcement, Company).join(Company, Company.id == Announcement.company_id)
        ).all()
    by_id = {a.source_id: (a, c) for a, c in rows}
    queue = [sid for sid in labelling_order(list(by_id)) if sid not in done][:n]
    typer.echo(f"{len(done)} already labelled or skipped; labelling {len(queue)} now.")
    typer.echo("Rules: use only the text, as the model must. See eval/README.md.\n")

    labelled = 0
    for i, sid in enumerate(queue, start=1):
        ann, company = by_id[sid]
        text = (settings.data_dir / ann.raw_text_uri).read_text(encoding="utf-8")
        accepted = ann.accepted_at.astimezone(EASTERN)
        typer.secho(
            f"\n[{i}/{len(queue)}] {company.ticker} {company.name}  {accepted:%Y-%m-%d %H:%M} ET"
            f"  {len(text):,} chars\n{ann.url}",
            bold=True,
        )
        typer.echo("-" * 80)
        typer.echo(text[:preview_chars])
        more = len(text) - preview_chars
        if more > 0 and typer.confirm(f"... {more:,} more chars. Show full text?", default=False):
            click.echo_via_pager(text)
        typer.echo("-" * 80)
        try:
            labels = ask_labels(lambda q: str(typer.prompt(q, prompt_suffix="")))
        except SkipDocument:
            record_skip(sid)
            typer.echo("skipped")
            continue
        except QuitLabelling:
            break
        notes = typer.prompt("Notes (optional)", default="", show_default=False)
        append_gold(
            GoldRecord(
                source=ann.source,
                source_id=sid,
                ticker=company.ticker,
                labels=labels,
                labeller=who,
                labelled_at=datetime.now(EASTERN),
                notes=notes,
            ),
            gold_path,
        )
        labelled += 1
    total = len(load_gold(gold_path))
    typer.echo(f"\nSaved {labelled} this session; gold set now has {total} labels ({gold_path}).")


@eval_app.command("run")
def eval_run(
    model: ModelOption = None,
    prompt_version: PromptVersionOption = "v1",
    gold_path: GoldOption = DEFAULT_GOLD,
) -> None:
    """Score a model/prompt on the gold set (extracting any gold documents it lacks)."""
    from newsalpha.eval.evaluate import GoldSetError, run_eval

    llm = _llm_setup(model, prompt_version)
    with Session(get_engine()) as session:
        try:
            run = run_eval(
                session=session,
                provider=llm.provider,
                model=llm.model,
                prompt=llm.prompt,
                price=llm.price,
                settings=llm.extraction,
                data_dir=get_settings().data_dir,
                gold_path=gold_path,
            )
        except GoldSetError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
    typer.echo(f"eval run {run.id}: {llm.model} / {llm.prompt.version} on {run.n_gold} gold docs")
    _print_metrics(run.metrics)


@eval_app.command("baseline")
def eval_baseline(
    model: ModelOption = None,
    prompt_version: PromptVersionOption = "v1",
    subset: Annotated[int, typer.Option("--subset", min=1)] = 20,
    threshold: Annotated[float, typer.Option("--threshold", min=0, max=1)] = 0.10,
    gold_path: GoldOption = DEFAULT_GOLD,
) -> None:
    """Freeze the first N gold documents and record reference scores for `eval regress`."""
    from sqlalchemy import select

    from newsalpha.db.models import Announcement, Company
    from newsalpha.eval.gold import load_gold
    from newsalpha.eval.regress import SubsetDoc, score_subset, write_baseline

    gold = load_gold(gold_path)[:subset]
    if len(gold) < subset:
        typer.secho(f"gold set has only {len(gold)} labels; need {subset}", fg="red", err=True)
        raise typer.Exit(2)
    llm = _llm_setup(model, prompt_version)
    settings = get_settings()
    docs = []
    with Session(get_engine()) as session:
        for g in gold:
            ann, company = session.execute(
                select(Announcement, Company)
                .join(Company, Company.id == Announcement.company_id)
                .where(Announcement.source == g.source, Announcement.source_id == g.source_id)
            ).one()
            text = (settings.data_dir / ann.raw_text_uri).read_text(encoding="utf-8")
            docs.append(SubsetDoc(g, company.name, text))
    metrics = score_subset(
        docs,
        provider=llm.provider,
        model=llm.model,
        prompt=llm.prompt,
        price=llm.price,
        settings=llm.extraction,
        sleep=time.sleep,
    )
    write_baseline(docs, metrics, llm.model, llm.prompt, threshold)
    typer.echo(f"baseline written for {llm.model}/{llm.prompt.version} on {len(docs)} docs")
    _print_metrics(metrics)


@eval_app.command("regress")
def eval_regress(gold_path: GoldOption = DEFAULT_GOLD) -> None:
    """Re-score the frozen subset and fail if accuracy regressed. Skips without an API key."""
    import json

    from newsalpha.eval.gold import load_gold
    from newsalpha.eval.regress import BASELINE_PATH, compare, load_subset, score_subset

    if not BASELINE_PATH.exists():
        typer.echo(f"no baseline at {BASELINE_PATH}; skipping (run `newsalpha eval baseline`)")
        return
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not get_settings().openai_api_key:
        typer.echo("OPENAI_API_KEY not set; skipping regression check")
        return
    llm = _llm_setup(baseline["model"], baseline["prompt_version"])
    docs = load_subset(baseline, load_gold(gold_path))
    metrics = score_subset(
        docs,
        provider=llm.provider,
        model=llm.model,
        prompt=llm.prompt,
        price=llm.price,
        settings=llm.extraction,
        sleep=time.sleep,
    )
    typer.echo(f"regression check: {llm.model}/{llm.prompt.version} on {len(docs)} docs")
    _print_metrics(metrics)
    problems = compare(baseline["metrics"], metrics, baseline["threshold"])
    for p in problems:
        typer.secho(f"  REGRESSION: {p}", fg=typer.colors.RED, err=True)
    if problems:
        raise typer.Exit(1)
    typer.echo("no regression")


if __name__ == "__main__":
    app()
