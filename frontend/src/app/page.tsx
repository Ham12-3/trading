import Link from "next/link";
import { connection } from "next/server";
import { ApiError, Card, GuidanceBadge, ToneBadge } from "@/components/ui";
import {
  apiGet,
  type Announcement,
  type AnnouncementPage,
  type BacktestGroup,
  type Company,
  type Health,
} from "@/lib/api";
import { etDateTime, num } from "@/lib/format";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-border bg-surface rounded-lg border p-4">
      <div className="text-muted text-xs">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

export default async function Overview() {
  await connection(); // live data, never prerendered
  const [health, companies, anns, latest, bt] = await Promise.all([
    apiGet<Health>("/health"),
    apiGet<Company[]>("/companies"),
    apiGet<AnnouncementPage>("/announcements?page_size=1"),
    apiGet<Announcement[]>("/signals/latest?limit=6"),
    apiGet<BacktestGroup>("/backtests?curves=false"),
  ]);
  const oos = bt.ok
    ? bt.data.runs.find((r) => r.strategy === "llm_composite" && r.period === "out_of_sample")
    : undefined;

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">NewsAlpha</h1>
        <p className="text-muted max-w-prose">
          Reads company earnings announcements, uses an LLM to turn each one into structured
          signals, then tests whether those signals predict stock returns over the following days.
          The LLM does the reading; the backtest decides whether the reading is worth anything.
        </p>
      </section>

      {!health.ok ? (
        <ApiError error={health.error} />
      ) : (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Companies" value={companies.ok ? String(companies.data.length) : "–"} />
          <Stat label="Announcements" value={anns.ok ? anns.data.total.toLocaleString() : "–"} />
          <Stat
            label="LLM strategy Sharpe, out-of-sample"
            value={oos ? num(oos.metrics.sharpe) : "–"}
          />
          <Stat label="System status" value={health.data.database === "ok" ? "OK" : "Degraded"} />
        </section>
      )}

      <Card title="Latest extracted signals">
        {!latest.ok ? (
          <ApiError error={latest.error} />
        ) : (
          <ul className="divide-border divide-y">
            {latest.data.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm">
                <Link href={`/announcements/${a.id}`} className="w-16 font-medium hover:underline">
                  {a.ticker}
                </Link>
                <span className="text-muted w-44 text-xs tabular-nums">
                  {etDateTime(a.accepted_at)}
                </span>
                {a.signal ? (
                  <>
                    <GuidanceBadge value={a.signal.guidance_direction} />
                    <ToneBadge value={a.signal.management_tone} />
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <Link href="/feed" className="text-accent mt-2 inline-block text-sm hover:underline">
          Full feed →
        </Link>
      </Card>
    </div>
  );
}
