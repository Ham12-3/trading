/**
 * Typed client for the NewsAlpha API. Types mirror the backend's Pydantic response models.
 *
 * Server components run inside the web container, where the API is reachable at API_URL
 * (e.g. http://api:8000). The browser uses NEXT_PUBLIC_API_URL.
 */

export function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export type Health = {
  status: "ok" | "degraded";
  database: "ok" | "unavailable";
  version: string;
};

export type Guidance = "raised" | "maintained" | "lowered" | "withdrawn" | "not_mentioned";
export type Expectation = "beat" | "inline" | "miss" | "unknown";

export type SignalSummary = {
  model: string;
  prompt_version: string;
  guidance_direction: Guidance;
  revenue_vs_expectation: Expectation;
  eps_vs_expectation: Expectation;
  management_tone: number;
  summary: string;
};

export type Eps = {
  eps_estimate: number | null;
  eps_reported: number | null;
  surprise_pct: number | null;
};

export type Announcement = {
  id: number;
  ticker: string;
  company_name: string;
  source: string;
  source_id: string;
  accepted_at: string;
  form_type: string;
  item_codes: string[];
  url: string;
  signal: SignalSummary | null;
  eps: Eps | null;
};

export type AnnouncementPage = {
  items: Announcement[];
  total: number;
  page: number;
  page_size: number;
};

export type SignalPayload = SignalSummary & {
  forward_looking_confidence: number;
  risk_flags: string[];
  key_quotes: string[];
  extraction_confidence: number;
};

export type Signal = {
  id: number;
  announcement_id: number;
  model: string;
  prompt_version: string;
  status: "ok" | "failed";
  payload: Omit<SignalPayload, "model" | "prompt_version"> | null;
  error: string | null;
  truncated: boolean;
  cache_hit: boolean;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  created_at: string;
};

export type EventRow = {
  t0_date: string;
  entry_price: number | null;
  gap_abnormal: number | null;
  ar_1: number | null;
  ar_3: number | null;
  ar_5: number | null;
};

export type AnnouncementDetail = Announcement & {
  text: string;
  text_available: boolean;
  signals: Signal[];
  event: EventRow | null;
};

export type Company = {
  id: number;
  ticker: string;
  name: string;
  cik: number;
  sector: string | null;
  exchange: string | null;
  n_announcements: number;
};

export type PeriodName = "all" | "in_sample" | "out_of_sample";

export type BucketStat = {
  grouping: string;
  bucket: string;
  window: number;
  n: number;
  mean_ar: number | null;
  std_ar: number | null;
  t_stat: number | null;
};

export type EventSummary = {
  model: string;
  prompt_version: string;
  period: PeriodName;
  periods: Record<"in_sample" | "out_of_sample", { start: string; end: string }>;
  n_events: number;
  stats: BucketStat[];
};

export type BacktestMetrics = {
  start: string;
  end: string;
  n_days: number;
  total_return: number;
  annualised_return: number;
  annualised_volatility: number;
  sharpe: number | null;
  max_drawdown: number;
  n_trades: number;
  n_long: number;
  n_short: number;
  hit_rate: number | null;
  mean_trade_net_return: number | null;
  skipped_capacity: number;
  skipped_no_prices: number;
  avg_positions: number;
  avg_gross_exposure: number;
  turnover_annual: number;
};

export type BacktestRun = {
  id: number;
  run_group: string;
  strategy: string;
  period: "in_sample" | "out_of_sample";
  metrics: BacktestMetrics;
  created_at: string;
  equity_curve: [string, number, number][] | null;
};

export type BacktestGroup = {
  run_group: string;
  created_at: string;
  config: {
    config: {
      signals: { model: string; prompt_version: string };
      periods: Record<"in_sample" | "out_of_sample", { start: string; end: string }>;
      baselines: { opening_gap_threshold: number };
      portfolio: {
        hold_days: number;
        max_positions: number;
        hedge_with_benchmark: boolean;
        cost_bps_per_side: number;
      };
    };
    fitted: {
      tone_center: number;
      weights: { guidance: number; tone: number; revenue: number; eps: number };
      long_threshold: number;
      short_threshold: number;
      tuned_on: string | null;
    };
    tuning_grid: { threshold: number; tone_weight: number; sharpe: number | null }[];
    n_events_with_signals: number;
  };
  runs: BacktestRun[];
};

export type EvalRun = {
  id: number;
  model: string;
  prompt_version: string;
  n_gold: number;
  gold_file: string;
  labellers: string[];
  created_at: string;
  mean_accuracy: number;
  accuracy: Record<string, number>;
  majority_baseline: Record<string, number>;
  management_tone_mae: number | null;
  schema_failure_rate: number;
  mean_cost_per_doc_usd: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
};

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const url = `${apiBaseUrl()}${path}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        // non-JSON error body: keep the status text
      }
      return { ok: false, error: `${res.status}: ${detail}`, status: res.status };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, error: `Could not reach ${url}: ${message}` };
  }
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
