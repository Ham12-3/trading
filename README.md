# NewsAlpha

An LLM signal lab for market announcements. It reads company earnings releases (SEC 8-K Item 2.02),
uses an LLM to turn each one into structured signals, and tests whether those signals predict stock
returns over the following days. The LLM does the reading; the backtest decides whether the reading
is worth anything.

**Research project only. No live trading, no investment advice.**

> Status: Phase 0 (scaffold). Full write-up, architecture diagram and results arrive in Phase 6.

## Quick start

```bash
cp .env.example .env          # fill in values as later phases need them
docker compose up --build     # db :5432, api :8000 (/docs), web :3000
```

Local development without Docker: see [CLAUDE.md](CLAUDE.md) for backend (`uv`) and frontend (`pnpm`) commands.
