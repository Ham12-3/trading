"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipContentProps, TooltipValueType } from "recharts";

export type SeriesDef = { key: string; name: string; color: string };
export type CurvePoint = { date: string } & Record<string, number | string>;

const tickStyle = { fill: "var(--ink-muted)", fontSize: 12 };

/** Named formats: functions cannot cross from Server to Client Components as props. */
export type CurveFormat = "equity" | "drawdown";
const FORMATS: Record<CurveFormat, (v: number) => string> = {
  equity: (v) => v.toFixed(3),
  drawdown: (v) => `${Number((v * 100).toFixed(2))}%`,
};

function CurveTooltip({
  active,
  payload,
  label,
  series,
  format,
}: TooltipContentProps<TooltipValueType, string | number> & {
  series: SeriesDef[];
  format: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as CurvePoint;
  return (
    <div className="border-border bg-surface rounded-md border px-3 py-2 text-xs shadow-sm">
      <div className="text-muted mb-1">{label}</div>
      {series.map((s) => (
        <div key={s.key} className="flex items-center gap-2 py-0.5">
          <span className="inline-block h-0.5 w-3" style={{ background: s.color }} />
          <span className="text-fg font-semibold tabular-nums">{format(Number(row[s.key]))}</span>
          <span className="text-muted">{s.name}</span>
        </div>
      ))}
    </div>
  );
}

/** One line per strategy on a single axis, with a crosshair tooltip listing every series. */
export function CurveChart({
  points,
  series,
  format: formatName,
  baseline,
  height = 256,
}: {
  points: CurvePoint[];
  series: SeriesDef[];
  format: CurveFormat;
  baseline?: number;
  height?: number;
}) {
  const format = FORMATS[formatName];
  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={tickStyle}
            axisLine={{ stroke: "var(--axis)" }}
            tickLine={false}
            minTickGap={48}
          />
          <YAxis
            tickFormatter={format}
            tick={tickStyle}
            axisLine={false}
            tickLine={false}
            width={56}
            domain={["auto", "auto"]}
          />
          {baseline !== undefined ? <ReferenceLine y={baseline} stroke="var(--axis)" /> : null}
          <Tooltip
            content={(props) => <CurveTooltip {...props} series={series} format={format} />}
            cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
          />
          <Legend
            itemSorter={null}
            iconType="plainline"
            iconSize={14}
            wrapperStyle={{ fontSize: 12, color: "var(--muted)" }}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              type="linear"
              dataKey={s.key}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
