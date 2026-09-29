import { ArBars, type ArRow } from "@/components/charts/ar-bars";
import { ApiError, Card, PageHeader, SegmentLinks } from "@/components/ui";
import { apiGet, query, type BucketStat, type EventSummary, type PeriodName } from "@/lib/api";
import { label, num, pct } from "@/lib/format";

const PERIODS: { value: PeriodName; label: string }[] = [
  { value: "all", label: "All" },
  { value: "in_sample", label: "In-sample" },
  { value: "out_of_sample", label: "Out-of-sample" },
];

const GROUP_NOTES: Record<string, string> = {
  guidance_direction: "LLM label: did the release raise, maintain or lower its outlook?",
  tone_tercile: "LLM management tone, split into terciles (cut points from in-sample events only).",
  beat_miss: "Only when the release itself compares results with expectations or guidance.",
  opening_gap: "Non-LLM: the stock's t0 opening gap vs SPY's (±1%). Known at entry.",
};

// Natural order for each grouping's buckets (bearish -> bullish), not alphabetical.
const BUCKET_ORDER = [
  "withdrawn",
  "lowered",
  "maintained",
  "not_mentioned",
  "raised",
  "low",
  "mid",
  "high",
  "miss",
  "neither",
  "beat",
  "gap down",
  "flat",
  "gap up",
];
const rank = (bucket: string) => {
  const i = BUCKET_ORDER.findIndex((b) => bucket === b || bucket.startsWith(`${b} (`));
  return i < 0 ? BUCKET_ORDER.length : i;
};

function toRows(stats: BucketStat[]): ArRow[] {
  const byBucket = new Map<string, ArRow>();
  for (const s of stats) {
    const row =
      byBucket.get(s.bucket) ??
      ({
        bucket: s.bucket,
        w1: null,
        w3: null,
        w5: null,
        n1: 0,
        n3: 0,
        n5: 0,
        t1: null,
        t3: null,
        t5: null,
      } as ArRow);
    const k = s.window as 1 | 3 | 5;
    row[`w${k}`] = s.mean_ar;
    row[`n${k}`] = s.n;
    row[`t${k}`] = s.t_stat;
    byBucket.set(s.bucket, row);
  }
  return [...byBucket.values()].sort((a, b) => rank(a.bucket) - rank(b.bucket));
}

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const period = (PERIODS.find((p) => p.value === sp.period)?.value ?? "all") as PeriodName;
  const res = await apiGet<EventSummary>(`/events/summary${query({ period })}`);

  return (
    <div>
      <PageHeader title="Event study">
        Mean abnormal return (stock minus SPY) from the t0 open, which is the first price a trader
        could act on, to the close of t0+k. Any move already in the opening gap is excluded. t-stats
        assume independent events; earnings cluster in time, so they overstate significance.
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SegmentLinks
          options={PERIODS}
          current={period}
          href={(v) => `/events${query({ period: v === "all" ? undefined : v })}`}
        />
        {res.ok ? (
          <span className="text-muted text-sm tabular-nums">
            {res.data.n_events.toLocaleString()} events · signals from {res.data.model} /{" "}
            {res.data.prompt_version} · in-sample {res.data.periods.in_sample.start} to{" "}
            {res.data.periods.in_sample.end}, out-of-sample {res.data.periods.out_of_sample.start}{" "}
            to {res.data.periods.out_of_sample.end}
          </span>
        ) : null}
      </div>

      {!res.ok ? (
        <ApiError error={res.error} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {Object.keys(GROUP_NOTES).map((grouping) => {
            const rows = toRows(res.data.stats.filter((s) => s.grouping === grouping));
            return (
              <Card key={grouping} title={label(grouping)}>
                <p className="text-muted mb-2 text-xs">{GROUP_NOTES[grouping]}</p>
                <ArBars rows={rows} />
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-xs tabular-nums">
                    <thead className="text-muted text-left">
                      <tr>
                        <th className="py-1 pr-2 font-medium">Bucket</th>
                        {[1, 3, 5].map((k) => (
                          <th key={k} className="py-1 pr-2 text-right font-medium">
                            t0+{k}: mean (t)
                          </th>
                        ))}
                        <th className="py-1 text-right font-medium">n</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.bucket} className="border-border border-t">
                          <td className="py-1 pr-2">{r.bucket}</td>
                          {([1, 3, 5] as const).map((k) => (
                            <td key={k} className="py-1 pr-2 text-right whitespace-nowrap">
                              {pct(r[`w${k}`])}{" "}
                              <span className="text-muted">({num(r[`t${k}`])})</span>
                            </td>
                          ))}
                          <td className="py-1 text-right">{r.n1}</td>
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
