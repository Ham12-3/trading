/**
 * Minimal typed client for the NewsAlpha API.
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

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const url = `${apiBaseUrl()}${path}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, error: `${res.status} ${res.statusText} from ${url}` };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, error: `Could not reach ${url}: ${message}` };
  }
}
