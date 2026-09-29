import { CurveChart, type CurvePoint, type SeriesDef } from "@/components/charts/equity-charts";
import { ApiError, Card, PageHeader, SegmentLinks } from "@/components/ui";
import { apiGet, query, type BacktestGroup, type BacktestRun } from "@/lib/api";
import { num, pct } from "@/lib/format";

type Period = "in_sample" | "out_of_sample";
const PERIODS: { value: Period; label: string }[] = [
  { value: "in_sample", label: "In-sample" },
  { value: "out_of_sample", label: "Out-of-sample" },
];

// Colour follows the strategy (not its rank), the same on every chart and period.
const SERIES: SeriesDef[] = [
  { key: "llm_composite", name: "LLM composite", color: "var(--series-1)" },
  { key: "baseline_opening_gap", name: "Baseline: opening gap", color: "var(--series-2)" },
  { key: "baseline_beat_miss", name: "Baseline: beat/miss", color: "var(--series-3)" },
];

function merge(runs: BacktestRun[], field: 1 | 2): CurvePoint[] {
  const byDate = new Map<string, CurvePoint>();
  for (const run of runs) {
    for (const point of run.equity_curve ?? []) {
      const row = byDate.get(point[0]) ?? ({ date: point[0] } as CurvePoint);
      row[run.strategy] = point[field];
      byDate.set(point[0], row);
    }
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export default async function BacktestPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const period: Period = sp.period === "in_sample" ? "in_sample" : "out_of_sample";
  const res = await apiGet<BacktestGroup>("/backtests");
  if (!res.ok) {
    return (
      <div>
        <PageHeader title="Backtest" />
        <ApiError error={res.error} />
      </div>
    );
  }
  const group = res.data;
  const cfg = group.config.config;
  const fit = group.config.fitted;
  const runs = group.runs.filter((r) => r.period === period);
  const nameOf = (key: string) => SERIES.find((s) => s.key === key)?.name ?? key;

  return (
    <div>
      <PageHeader title="Backtest">
        Each event: long if the signal is positive, short if negative, flat otherwise. Enter at the
        t0 open, exit at the close of t0+{cfg.portfolio.hold_days}. Positions are{" "}
        {pct(1 / cfg.portfolio.max_positions, 0, false)} of capital each
        {cfg.portfolio.hedge_with_benchmark ? ", hedged with SPY" : ""}, and{" "}
        {cfg.portfolio.cost_bps_per_side} bps are charged per side on every leg. Parameters were
        tuned on the in-sample period only; out-of-sample was run once.
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SegmentLinks
          options={PERIODS}
          current={period}
          href={(v) => `/backtest${query({ period: v === "out_of_sample" ? undefined : v })}`}
        />
        <span className="text-muted text-sm tabular-nums">
          {cfg.periods[period].start} to {cfg.periods[period].end} · run{" "}
          {group.run_group.slice(0, 8)} · {new Date(group.created_at).toLocaleDateString("en-US")}
        </span>
      </div>

      <div className="grid gap-4">
        <Card title="Equity (starting capital = 1)">
          <CurveChart points={merge(runs, 1)} series={SERIES} format="equity" baseline={1} />
        </Card>
        <Card title="Drawdown from peak">
          <CurveChart
            points={merge(runs, 2)}
            series={SERIES}
            format="drawdown"
            baseline={0}
            height={180}
          />
        </Card>

        <Card title="Metrics (both periods)">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-xs tabular-nums">
              <thead className="text-muted text-left">
                <tr>
                  {[
                    "Strategy",
                    "Period",
                    "Ann. return",
                    "Volatility",
                    "Sharpe",
                    "Max DD",
                    "Hit rate",
                    "Trades (L/S)",
                    "Net / trade",
                    "Avg exposure",
                    "Turnover / yr",
                  ].map((h) => (
                    <th key={h} className="py-1 pr-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {group.runs.map((r) => {
                  const m = r.metrics;
                  return (
                    <tr
                      key={r.id}
                      className={`border-border border-t ${r.period === period ? "" : "text-muted"}`}
                    >
                      <td className="py-1 pr-3 whitespace-nowrap">{nameOf(r.strategy)}</td>
                      <td className="py-1 pr-3 whitespace-nowrap">
                        {r.period === "in_sample" ? "In-sample" : "Out-of-sample"}
                      </td>
                      <td className="py-1 pr-3">{pct(m.annualised_return)}</td>
                      <td className="py-1 pr-3">{pct(m.annualised_volatility, 2, false)}</td>
                      <td className="py-1 pr-3">{num(m.sharpe)}</td>
                      <td className="py-1 pr-3">{pct(m.max_drawdown)}</td>
                      <td className="py-1 pr-3">{pct(m.hit_rate, 0, false)}</td>
                      <td className="py-1 pr-3">
                        {m.n_trades} ({m.n_long}/{m.n_short})
                      </td>
                      <td className="py-1 pr-3">{pct(m.mean_trade_net_return)}</td>
                      <td className="py-1 pr-3">{pct(m.avg_gross_exposure, 1, false)}</td>
                      <td className="py-1 pr-3">{num(m.turnover_annual, 1)}×</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-muted mt-2 text-xs">
            Sharpe uses a zero risk-free rate. Low average exposure means small absolute returns;
            Sharpe and net return per trade are the comparable figures.
          </p>
        </Card>

        <Card title="LLM composite: fitted on in-sample">
          <p className="text-sm">
            score = {fit.weights.guidance} × guidance + {fit.weights.tone} × (tone −{" "}
            {num(fit.tone_center)}) + {fit.weights.revenue} × revenue + {fit.weights.eps} × EPS;
            long above {fit.long_threshold}, short below {fit.short_threshold}.
          </p>
          <p className="text-muted mt-1 text-xs">
            Guidance raised = +1, lowered/withdrawn = −1; beat = +1, miss = −1. Signals from{" "}
            {cfg.signals.model} / {cfg.signals.prompt_version} on{" "}
            {group.config.n_events_with_signals.toLocaleString()} events. The tuning grid picked the
            best in-sample Sharpe of {group.config.tuning_grid.length} combinations.
          </p>
        </Card>
      </div>
    </div>
  );
}
