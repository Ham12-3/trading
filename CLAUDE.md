# NewsAlpha — CLAUDE.md

LLM signal lab: read company announcements (SEC 8-K Item 2.02 / Ex-99.1), extract structured
signals with an LLM, and test whether they predict returns. **Research only — no live trading,
no broker integration, no investment-advice features.**

The full spec is the PRD (owner: Abdulhamid Sonaike). This file holds the rules that must never drift.

## Working agreement

- Work **one phase at a time** (phases 0–7, PRD §17). Before coding a phase, write a short plan
  listing files to create/change. At the end of a phase: run tests + linters, summarise, **stop for review**.
- Commit after each working step with a clear message.
- **Never invent or fake data.** If a source fails, surface the error clearly. No placeholder numbers in the dashboard.
- If a requirement is unclear or conflicts with another, **ask** instead of guessing.
- Prefer small, readable modules with type hints and docstrings over clever code.
- Never hardcode secrets. Config comes from `.env` (see `.env.example`). `.env` is gitignored.

## Point-in-time rules (non-negotiable, each must have tests)

1. Every signal is tied to the announcement's EDGAR **acceptance timestamp**.
2. Event day t0 (US/Eastern, exchange calendar):
   - accepted **before 09:30 ET on a trading day** → t0 = that day, entry at that day's **open**;
   - accepted during market hours, after the close, or on a non-trading day → t0 = **next** trading day, entry at its **open**.
3. Never use price, fundamental or text data timestamped after the entry time when computing a signal.
4. Use a real exchange calendar (`pandas_market_calendars`, XNYS) for holidays and early closes.
5. The universe must not be selected with future information (survivorship bias is a documented v1 limitation).

Tests must cover pre-market, intraday, after-close, weekend and holiday cases, plus a
"lookahead trap" test that injects a future price and asserts it is not used.

## LLM rules

- LLM only reads and labels text. **Deterministic maths stays in Python** (returns, ratios, weights).
- Anthropic SDK with tool use / structured output; validate with Pydantic (`AnnouncementSignals`, PRD §8.1).
  On validation failure: retry once with the error in the prompt, then mark row `failed` and move on.
- Prompts are versioned files in `backend/prompts/` (`extract_v1.md`, …). Store `model` + `prompt_version` on every signal row.
- Cache key: `(document_hash, model, prompt_version)` — never pay for the same extraction twice.
- Record input/output tokens, cost (price table in config), latency for every call.
- Concurrency limit + exponential backoff on rate limits. Log truncation of long documents.
- Default models (config): `claude-haiku-4-5-20251001` (bulk), `claude-sonnet-5` (comparison / hard cases).
- **No live LLM calls in the default test suite** — use recorded fixtures.

## Data sources

- SEC EDGAR: official endpoints, `User-Agent` = name + email from config, ≤10 req/s (default 5).
- Prices: daily OHLCV adjusted, `yfinance` behind a `PriceSource` interface. Benchmark SPY.
- Sources sit behind `AnnouncementSource` / `PriceSource` interfaces (UK source is a later phase; check licensing first).

## Backtest honesty

- Abnormal return = stock return − benchmark return; windows [t0,t0+1], [t0,t0+3], [t0,t0+5] from entry price.
- Costs default 10 bps/side. Always report a non-LLM baseline. In-sample vs held-out out-of-sample, both reported.
- Show results even when weak/negative. List limitations on the results page.

## Layout

```
backend/            Python 3.12, uv
  src/newsalpha/
    core/           config, calendar, time rules, pure maths   (mypy --strict)
    sources/        AnnouncementSource, PriceSource, EDGAR, yfinance
    extraction/     LLM client, schema, prompt loader, cache, cost tracking
    backtest/       event study, portfolio, metrics
    eval/           labelling, scoring
    db/             SQLAlchemy models, session, Alembic migrations (db/migrations)
    api/            FastAPI app + routers
    cli.py          Typer entrypoint (`newsalpha ...`)
  prompts/  config/  tests/
frontend/           Next.js App Router, TypeScript, Tailwind, Recharts
eval/gold/          hand-labelled gold set (*.jsonl)
docker-compose.yml  postgres, api, web
```

All DB schema changes go through Alembic.

## Commands

Backend (run from `backend/`):

```bash
uv sync                                   # install deps
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict on core/, checked elsewhere
uv run pytest                             # default suite: no network, no LLM calls
uv run alembic upgrade head               # apply migrations (needs DATABASE_URL)
uv run uvicorn newsalpha.api.app:app --reload
uv run newsalpha --help
```

Frontend (run from `frontend/`):

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm lint && pnpm typecheck && pnpm format:check
pnpm build
```

Everything:

```bash
docker compose up --build    # postgres :5432, api :8000 (/docs), web :3000
```

A phase is done only when `pytest`, `ruff`, `mypy` (and frontend lint/typecheck/build) are clean.
