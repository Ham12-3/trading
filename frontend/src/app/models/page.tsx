import { connection } from "next/server";
import { ApiError, Card, PageHeader } from "@/components/ui";
import { apiGet, type EvalRun } from "@/lib/api";
import { label, num, pct, usd } from "@/lib/format";

const FIELDS = ["guidance_direction", "revenue_vs_expectation", "eps_vs_expectation"];

export default async function ModelsPage() {
  await connection();
  const res = await apiGet<EvalRun[]>("/evals");

  return (
    <div>
      <PageHeader title="Models">
        Extraction quality, cost and latency per model and prompt version, scored on a labelled
        sample of releases. The always-majority column is the score of always giving the most common
        label; only the gap above it is informative.
      </PageHeader>
      {!res.ok ? (
        <ApiError error={res.error} />
      ) : res.data.length === 0 ? (
        <p className="text-muted text-sm">No eval runs yet. Run `newsalpha eval run`.</p>
      ) : (
        <div className="space-y-4">
          {[...new Set(res.data.map((r) => r.labellers.join(", ")))].map((labellers) => {
            const runs = res.data.filter((r) => r.labellers.join(", ") === labellers);
            const modelMade = runs[0].labellers.some((l) => l.startsWith("claude"));
            return (
              <Card
                key={labellers}
                title={`Labels: ${runs[0].gold_file} (${runs[0].n_gold} releases) by ${labellers}`}
              >
                {modelMade ? (
                  <p className="text-warn mb-3 text-xs">
                    These labels were produced by a model ({labellers}), not a human. Scores are
                    agreement with those labels, not accuracy against human judgement.
                  </p>
                ) : null}
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-sm tabular-nums">
                    <thead className="text-muted text-left text-xs">
                      <tr>
                        <th className="py-1 pr-3 font-medium">Metric</th>
                        {runs.map((r) => (
                          <th key={r.id} className="py-1 pr-3 text-right font-medium">
                            {r.model} · {r.prompt_version}
                          </th>
                        ))}
                        <th className="py-1 text-right font-medium">Always-majority</th>
                      </tr>
                    </thead>
                    <tbody>
                      {FIELDS.map((f) => (
                        <tr key={f} className="border-border border-t">
                          <td className="py-1 pr-3">{label(f)}</td>
                          {runs.map((r) => (
                            <td key={r.id} className="py-1 pr-3 text-right">
                              {pct(r.accuracy[f], 1, false)}
                            </td>
                          ))}
                          <td className="text-muted py-1 text-right">
                            {pct(runs[0].majority_baseline[f], 1, false)}
                          </td>
                        </tr>
                      ))}
                      {[
                        ["Tone mean abs. error", (r: EvalRun) => num(r.management_tone_mae, 3)],
                        [
                          "Schema failure rate",
                          (r: EvalRun) => pct(r.schema_failure_rate, 1, false),
                        ],
                        ["Cost per release", (r: EvalRun) => usd(r.mean_cost_per_doc_usd)],
                        [
                          "Latency p50 / p95",
                          (r: EvalRun) =>
                            r.latency_p50_ms === null || r.latency_p95_ms === null
                              ? "–"
                              : `${(r.latency_p50_ms / 1000).toFixed(1)}s / ${(r.latency_p95_ms / 1000).toFixed(1)}s`,
                        ],
                      ].map(([name, fmt]) => (
                        <tr key={name as string} className="border-border border-t">
                          <td className="py-1 pr-3">{name as string}</td>
                          {runs.map((r) => (
                            <td key={r.id} className="py-1 pr-3 text-right">
                              {(fmt as (r: EvalRun) => string)(r)}
                            </td>
                          ))}
                          <td />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
