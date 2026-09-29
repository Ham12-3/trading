import Link from "next/link";
import type { ReactNode } from "react";
import type { Eps, Expectation, Guidance } from "@/lib/api";
import { label, num, pct } from "@/lib/format";

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-6 space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {children ? <div className="text-muted max-w-prose text-sm">{children}</div> : null}
    </header>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="border-border bg-surface min-w-0 rounded-lg border p-4">
      {title ? <h2 className="mb-3 text-sm font-medium">{title}</h2> : null}
      {children}
    </section>
  );
}

/** Surfaces an API failure as-is; pages never fall back to made-up numbers. */
export function ApiError({ error }: { error: string }) {
  return (
    <div className="border-negative/40 text-negative rounded-lg border p-4 text-sm break-words">
      Could not load data. {error}
    </div>
  );
}

/** A row of links that set one query parameter; the current value is marked. */
export function SegmentLinks({
  options,
  current,
  href,
}: {
  options: { value: string; label: string }[];
  current: string;
  href: (value: string) => string;
}) {
  return (
    <div className="border-border inline-flex rounded-md border p-0.5 text-sm" role="group">
      {options.map((o) => (
        <Link
          key={o.value}
          href={href(o.value)}
          aria-current={o.value === current ? "true" : undefined}
          className={`rounded px-3 py-1 ${
            o.value === current ? "bg-fg text-bg" : "text-muted hover:text-fg"
          }`}
        >
          {o.label}
        </Link>
      ))}
    </div>
  );
}

const GUIDANCE: Record<Guidance, { icon: string; cls: string }> = {
  raised: { icon: "▲", cls: "text-positive" },
  lowered: { icon: "▼", cls: "text-negative" },
  withdrawn: { icon: "✕", cls: "text-negative" },
  maintained: { icon: "=", cls: "text-fg" },
  not_mentioned: { icon: "·", cls: "text-muted" },
};

/** Icon + word, so the colour is never the only cue. */
export function GuidanceBadge({ value }: { value: Guidance }) {
  const g = GUIDANCE[value];
  return (
    <span className={`inline-flex items-center gap-1 text-xs whitespace-nowrap ${g.cls}`}>
      <span aria-hidden>{g.icon}</span>
      {label(value)}
    </span>
  );
}

export function ExpectationText({ value }: { value: Expectation }) {
  const cls =
    value === "beat" ? "text-positive" : value === "miss" ? "text-negative" : "text-muted";
  return <span className={`text-xs ${cls}`}>{value}</span>;
}

/** Numeric EPS surprise vs analyst consensus (not from the LLM); within ±2% is inline. */
export function EpsSurprise({ eps }: { eps: Eps | null }) {
  if (!eps || eps.surprise_pct === null) return <span className="text-muted text-xs">–</span>;
  const s = eps.surprise_pct;
  const verdict = s > 0.02 ? "beat" : s < -0.02 ? "miss" : "inline";
  return (
    <span className="text-xs whitespace-nowrap tabular-nums">
      <ExpectationText value={verdict} /> <span className="text-muted">{pct(s, 1)}</span>
    </span>
  );
}

/** Tone in [-1, 1] as a signed number with a word; a small bar shows where it sits. */
export function ToneBadge({ value }: { value: number }) {
  const word =
    value >= 0.5 ? "upbeat" : value > 0.1 ? "positive" : value >= -0.1 ? "neutral" : "negative";
  return (
    <span className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
      <span className="bg-border relative h-1.5 w-12 rounded-full" aria-hidden>
        <span
          className="bg-fg absolute top-0 h-1.5 w-1.5 rounded-full"
          style={{ left: `calc(${((value + 1) / 2) * 100}% - 3px)` }}
        />
      </span>
      <span className="tabular-nums">{num(value)}</span>
      <span className="text-muted">{word}</span>
    </span>
  );
}
