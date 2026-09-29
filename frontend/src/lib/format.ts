/** Display formatting. Times are shown in US/Eastern, the market's clock. */

export function pct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const s = (v * 100).toFixed(digits) + "%";
  return signed && v > 0 ? `+${s}` : s;
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toFixed(digits);
}

export function usd(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return "–";
  return `$${v.toFixed(digits)}`;
}

const ET = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function etDateTime(iso: string): string {
  return `${ET.format(new Date(iso))} ET`;
}

export function label(snake: string): string {
  const s = snake.replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
