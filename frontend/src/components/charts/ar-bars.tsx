"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Rectangle,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BarShapeProps, TooltipContentProps, TooltipValueType } from "recharts";

export type ArRow = {
  bucket: string;
  w1: number | null;
  w3: number | null;
  w5: number | null;
  n1: number;
  n3: number;
  n5: number;
  t1: number | null;
  t3: number | null;
  t5: number | null;
};

const WINDOWS = [
  { key: "w1", n: "n1", t: "t1", name: "[t0, t0+1]", color: "var(--series-1)" },
  { key: "w3", n: "n3", t: "t3", name: "[t0, t0+3]", color: "var(--series-2)" },
  { key: "w5", n: "n5", t: "t5", name: "[t0, t0+5]", color: "var(--series-3)" },
] as const;

// Up to two decimals, trailing zeros trimmed: ticks at -0.15% must not round to a duplicate label.
const pctTick = (v: number) => `${Number((v * 100).toFixed(2))}%`;

/** Round the data end (top for positive, bottom for negative); square at the baseline. */
function DataEndBar(props: BarShapeProps) {
  const negative = Number(props.value) < 0;
  return <Rectangle {...props} radius={negative ? [0, 0, 4, 4] : [4, 4, 0, 0]} />;
}

function ArTooltip({
  active,
  payload,
  label,
}: TooltipContentProps<TooltipValueType, string | number>) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as ArRow;
  return (
    <div className="border-border bg-surface rounded-md border px-3 py-2 text-xs shadow-sm">
      <div className="text-muted mb-1">{label}</div>
      {WINDOWS.map((w) => {
        const v = row[w.key];
        return (
          <div key={w.key} className="flex items-center gap-2 py-0.5">
            <span className="inline-block h-0.5 w-3" style={{ background: w.color }} />
            <span className="text-fg font-semibold tabular-nums">
              {v === null ? "–" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`}
            </span>
            <span className="text-muted">
              {w.name} · n {row[w.n]} · t {row[w.t] === null ? "–" : row[w.t]!.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Mean abnormal return per bucket; one bar per window. Values also in the table below. */
export function ArBars({ rows }: { rows: ArRow[] }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="bucket"
            tick={{ fill: "var(--ink-muted)", fontSize: 12 }}
            axisLine={{ stroke: "var(--axis)" }}
            tickLine={false}
            interval={0}
          />
          <YAxis
            tickFormatter={pctTick}
            tick={{ fill: "var(--ink-muted)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={48}
          />
          <ReferenceLine y={0} stroke="var(--axis)" />
          <Tooltip content={ArTooltip} cursor={{ fill: "var(--grid)", opacity: 0.4 }} />
          <Legend
            itemSorter={null}
            iconType="rect"
            iconSize={10}
            wrapperStyle={{ fontSize: 12, color: "var(--muted)" }}
          />
          {WINDOWS.map((w) => (
            <Bar
              key={w.key}
              dataKey={w.key}
              name={w.name}
              fill={w.color}
              maxBarSize={18}
              shape={DataEndBar}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
