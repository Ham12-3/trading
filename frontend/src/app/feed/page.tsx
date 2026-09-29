import Link from "next/link";
import { ApiError, ExpectationText, GuidanceBadge, PageHeader, ToneBadge } from "@/components/ui";
import { apiGet, query, type AnnouncementPage, type Company } from "@/lib/api";
import { etDateTime } from "@/lib/format";

const PAGE_SIZE = 25;

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const ticker = typeof sp.ticker === "string" ? sp.ticker : "";
  const page = Math.max(1, Number(typeof sp.page === "string" ? sp.page : 1) || 1);

  const [list, companies] = await Promise.all([
    apiGet<AnnouncementPage>(`/announcements${query({ ticker, page, page_size: PAGE_SIZE })}`),
    apiGet<Company[]>("/companies"),
  ]);

  const pageHref = (p: number) => `/feed${query({ ticker, page: p })}`;

  return (
    <div>
      <PageHeader title="Feed">
        Earnings releases (SEC 8-K Item 2.02, Exhibit 99.1), newest first, with the signals the LLM
        extracted from each. Times are the SEC acceptance timestamp in US/Eastern.
      </PageHeader>

      <form method="get" className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="ticker" className="text-muted">
          Company
        </label>
        <select
          id="ticker"
          name="ticker"
          defaultValue={ticker}
          className="border-border bg-surface rounded-md border px-2 py-1"
        >
          <option value="">All companies</option>
          {companies.ok
            ? companies.data.map((c) => (
                <option key={c.ticker} value={c.ticker}>
                  {c.ticker} · {c.name}
                </option>
              ))
            : null}
        </select>
        <button
          type="submit"
          className="border-border hover:bg-surface rounded-md border px-3 py-1"
        >
          Apply
        </button>
      </form>

      {!list.ok ? (
        <ApiError error={list.error} />
      ) : (
        <>
          <div className="border-border bg-surface overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-muted text-left text-xs">
                <tr className="border-border border-b">
                  <th className="px-3 py-2 font-medium">Accepted</th>
                  <th className="px-3 py-2 font-medium">Company</th>
                  <th className="px-3 py-2 font-medium">Guidance</th>
                  <th className="px-3 py-2 font-medium">Tone</th>
                  <th className="px-3 py-2 font-medium">Rev / EPS vs exp.</th>
                  <th className="px-3 py-2 font-medium">Summary</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id} className="border-border border-b align-top last:border-0">
                    <td className="text-muted px-3 py-2 text-xs whitespace-nowrap tabular-nums">
                      {etDateTime(a.accepted_at)}
                    </td>
                    <td className="px-3 py-2">
                      <Link href={`/announcements/${a.id}`} className="font-medium hover:underline">
                        {a.ticker}
                      </Link>
                      <div className="text-muted text-xs">{a.company_name}</div>
                    </td>
                    {a.signal ? (
                      <>
                        <td className="px-3 py-2">
                          <GuidanceBadge value={a.signal.guidance_direction} />
                        </td>
                        <td className="px-3 py-2">
                          <ToneBadge value={a.signal.management_tone} />
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <ExpectationText value={a.signal.revenue_vs_expectation} />
                          <span className="text-muted"> / </span>
                          <ExpectationText value={a.signal.eps_vs_expectation} />
                        </td>
                        <td className="text-muted max-w-md px-3 py-2 text-xs">
                          {a.signal.summary}
                          <a
                            href={a.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-accent ml-1 whitespace-nowrap hover:underline"
                          >
                            SEC filing ↗
                          </a>
                        </td>
                      </>
                    ) : (
                      <td colSpan={4} className="text-muted px-3 py-2 text-xs">
                        No extracted signal yet.{" "}
                        <a href={a.url} target="_blank" rel="noreferrer" className="text-accent">
                          SEC filing ↗
                        </a>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="text-muted mt-3 flex items-center justify-between text-sm">
            <span className="tabular-nums">
              {list.data.total === 0
                ? "No announcements"
                : `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, list.data.total)} of ${list.data.total}`}
            </span>
            <span className="flex gap-3">
              {page > 1 ? (
                <Link href={pageHref(page - 1)} className="hover:text-fg">
                  ← Newer
                </Link>
              ) : null}
              {page * PAGE_SIZE < list.data.total ? (
                <Link href={pageHref(page + 1)} className="hover:text-fg">
                  Older →
                </Link>
              ) : null}
            </span>
          </nav>
        </>
      )}
    </div>
  );
}
