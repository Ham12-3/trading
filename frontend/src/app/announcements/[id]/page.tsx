import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import type { ReactNode } from "react";
import { ApiError, Card, EpsSurprise, GuidanceBadge, PageHeader, ToneBadge } from "@/components/ui";
import { apiBaseUrl, apiGet, type AnnouncementDetail } from "@/lib/api";
import { etDateTime, pct, usd } from "@/lib/format";

/** Split text into plain and highlighted parts wherever a key quote appears verbatim. */
function highlight(text: string, quotes: string[]): { nodes: ReactNode[]; found: Set<string> } {
  const found = new Set<string>();
  const hits: { start: number; end: number }[] = [];
  for (const q of quotes) {
    const needle = q.replace(/^["'“”]+|["'“”]+$/g, "").trim();
    if (!needle) continue;
    const at = text.indexOf(needle);
    if (at >= 0) {
      found.add(q);
      hits.push({ start: at, end: at + needle.length });
    }
  }
  hits.sort((a, b) => a.start - b.start);
  const nodes: ReactNode[] = [];
  let pos = 0;
  hits.forEach((h, i) => {
    if (h.start < pos) return; // overlapping quote: keep the first
    nodes.push(text.slice(pos, h.start));
    nodes.push(
      <mark key={i} className="bg-highlight text-fg rounded-sm">
        {text.slice(h.start, h.end)}
      </mark>,
    );
    pos = h.end;
  });
  nodes.push(text.slice(pos));
  return { nodes, found };
}

async function extractNow(id: number) {
  "use server";
  await fetch(`${apiBaseUrl()}/extract/${id}`, { method: "POST", cache: "no-store" });
  redirect(`/announcements/${id}`);
}

export default async function AnnouncementPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const res = await apiGet<AnnouncementDetail>(`/announcements/${id}`);
  if (!res.ok) {
    if (res.status === 404) notFound();
    return <ApiError error={res.error} />;
  }
  const a = res.data;
  const current = a.signals.find(
    (s) => a.signal && s.model === a.signal.model && s.prompt_version === a.signal.prompt_version,
  );
  const quotes = current?.payload?.key_quotes ?? [];
  const { nodes, found } = highlight(a.text, quotes);

  return (
    <div>
      <Link href="/feed" className="text-muted hover:text-fg text-sm">
        ← Feed
      </Link>
      <PageHeader title={`${a.ticker} · ${a.company_name}`}>
        Accepted {etDateTime(a.accepted_at)} · {a.form_type} items {a.item_codes.join(", ")} ·{" "}
        <a href={a.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
          SEC filing ↗
        </a>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card title="Exhibit 99.1 text">
          {a.text_available ? (
            <div className="max-h-[70vh] overflow-y-auto font-mono text-xs leading-relaxed whitespace-pre-wrap">
              {nodes}
            </div>
          ) : (
            <p className="text-negative text-sm">Stored text file not found on the API server.</p>
          )}
        </Card>

        <div className="space-y-4">
          {a.signal && current?.payload ? (
            <Card title={`Signals · ${current.model} · prompt ${current.prompt_version}`}>
              <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted">Guidance</dt>
                <dd>
                  <GuidanceBadge value={a.signal.guidance_direction} />
                </dd>
                <dt className="text-muted">Tone</dt>
                <dd>
                  <ToneBadge value={a.signal.management_tone} />
                </dd>
                <dt className="text-muted">Revenue / EPS</dt>
                <dd className="text-xs">
                  {a.signal.revenue_vs_expectation} / {a.signal.eps_vs_expectation}
                </dd>
              </dl>
              <h3 className="text-muted mb-1 text-xs font-medium">Key quotes</h3>
              <ul className="mb-3 space-y-1 text-xs">
                {quotes.map((q) => (
                  <li key={q}>
                    <mark className="bg-highlight text-fg rounded-sm">{q}</mark>
                    {found.has(q) ? null : (
                      <span className="text-muted"> (not found verbatim in the text)</span>
                    )}
                  </li>
                ))}
              </ul>
              <h3 className="text-muted mb-1 text-xs font-medium">Extracted JSON</h3>
              <pre className="bg-bg max-h-80 overflow-auto rounded-md p-2 text-xs">
                {JSON.stringify(current.payload, null, 2)}
              </pre>
              <p className="text-muted mt-2 text-xs tabular-nums">
                {current.input_tokens.toLocaleString()} in /{" "}
                {current.output_tokens.toLocaleString()} out tokens · {usd(current.cost_usd)} ·{" "}
                {(current.latency_ms / 1000).toFixed(1)}s
                {current.truncated ? " · document truncated" : ""}
                {current.cache_hit ? " · from cache" : ""}
              </p>
            </Card>
          ) : (
            <Card title="Signals">
              <p className="text-muted mb-3 text-sm">
                No extracted signal for the default model yet
                {current?.status === "failed" ? ` (last attempt failed: ${current.error})` : ""}.
              </p>
              <form action={extractNow.bind(null, a.id)}>
                <button className="border-border hover:bg-bg rounded-md border px-3 py-1 text-sm">
                  Extract now (calls the LLM API)
                </button>
              </form>
            </Card>
          )}

          {a.eps ? (
            <Card title="EPS vs analyst consensus (not from the LLM)">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm tabular-nums">
                <dt className="text-muted">Reported EPS</dt>
                <dd>{a.eps.eps_reported === null ? "–" : `$${a.eps.eps_reported.toFixed(2)}`}</dd>
                <dt className="text-muted">Consensus estimate</dt>
                <dd>{a.eps.eps_estimate === null ? "–" : `$${a.eps.eps_estimate.toFixed(2)}`}</dd>
                <dt className="text-muted">Surprise</dt>
                <dd>
                  <EpsSurprise eps={a.eps} />
                </dd>
              </dl>
              <p className="text-muted mt-2 text-xs">
                Source: Yahoo Finance consensus around the report date. Within ±2% counts as inline.
              </p>
            </Card>
          ) : null}

          {a.event ? (
            <Card title="Event">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm tabular-nums">
                <dt className="text-muted">t0 (entry at open)</dt>
                <dd>{a.event.t0_date}</dd>
                <dt className="text-muted">Opening gap vs SPY</dt>
                <dd>{pct(a.event.gap_abnormal)}</dd>
                <dt className="text-muted">Abnormal return [t0, t0+1]</dt>
                <dd>{pct(a.event.ar_1)}</dd>
                <dt className="text-muted">Abnormal return [t0, t0+3]</dt>
                <dd>{pct(a.event.ar_3)}</dd>
                <dt className="text-muted">Abnormal return [t0, t0+5]</dt>
                <dd>{pct(a.event.ar_5)}</dd>
              </dl>
            </Card>
          ) : null}

          {a.signals.length > 1 ? (
            <Card title="All extractions of this release">
              <ul className="space-y-1 text-xs">
                {a.signals.map((s) => (
                  <li key={s.id} className="flex justify-between gap-2">
                    <span>
                      {s.model} · {s.prompt_version}
                    </span>
                    <span className={s.status === "ok" ? "text-muted" : "text-negative"}>
                      {s.status} · {usd(s.cost_usd)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
