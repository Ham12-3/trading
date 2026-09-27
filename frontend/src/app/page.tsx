import { connection } from "next/server";
import { apiGet, type Health } from "@/lib/api";

export default async function Overview() {
  await connection(); // health is per-request, never prerendered
  const health = await apiGet<Health>("/health");

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

      <section className="border-border bg-surface rounded-lg border p-4">
        <h2 className="text-muted mb-3 text-sm font-medium">System status</h2>
        {health.ok ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            <dt className="text-muted">API</dt>
            <dd className={health.data.status === "ok" ? "text-positive" : "text-warn"}>
              {health.data.status} (v{health.data.version})
            </dd>
            <dt className="text-muted">Database</dt>
            <dd className={health.data.database === "ok" ? "text-positive" : "text-negative"}>
              {health.data.database}
            </dd>
          </dl>
        ) : (
          <p className="text-negative text-sm break-words">API unreachable. {health.error}</p>
        )}
      </section>
    </div>
  );
}
