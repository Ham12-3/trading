import { connection } from "next/server";
import { Card, PageHeader } from "@/components/ui";
import { apiGet, type AnnouncementPage, type BacktestGroup, type Company } from "@/lib/api";

export default async function AboutPage() {
  await connection();
  const [companies, anns, bt] = await Promise.all([
    apiGet<Company[]>("/companies"),
    apiGet<AnnouncementPage>("/announcements?page_size=1"),
    apiGet<BacktestGroup>("/backtests?curves=false"),
  ]);
  const cfg = bt.ok ? bt.data.config.config : null;

  return (
    <div className="max-w-3xl">
      <PageHeader title="About and limitations">
        What NewsAlpha does, how, and why its results should be read with care. Research only: no
        trades are placed and nothing here is investment advice.
      </PageHeader>

      <div className="space-y-4 text-sm leading-relaxed">
        <Card title="Method">
          <ol className="list-decimal space-y-2 pl-5">
            <li>
              <b>Announcements.</b> SEC EDGAR 8-K filings with Item 2.02 (results of operations),
              using the Exhibit 99.1 press release text
              {companies.ok && anns.ok
                ? `: ${anns.data.total.toLocaleString()} releases from ${companies.data.length} companies`
                : ""}
              . The SEC acceptance timestamp is the point-in-time anchor.
            </li>
            <li>
              <b>Event day.</b> A release accepted before 09:30 ET on a trading day trades that day;
              anything later trades the next trading day (NYSE calendar, holidays and early closes
              included). Entry is always at that day&apos;s open.
            </li>
            <li>
              <b>Extraction.</b> An LLM reads each release and returns a schema-validated set of
              labels: guidance direction, revenue/EPS vs expectations, management tone, risk flags
              and supporting quotes. It is told to use only the text. All maths stays in Python.
            </li>
            <li>
              <b>Evaluation.</b> Extraction is scored against a labelled sample (Models page).
            </li>
            <li>
              <b>Event study and backtest.</b> Abnormal returns vs SPY from the entry open; a
              long/short book with costs, compared against non-LLM baselines, tuned in-sample and
              reported out-of-sample
              {cfg
                ? ` (in-sample ${cfg.periods.in_sample.start} to ${cfg.periods.in_sample.end}; out-of-sample ${cfg.periods.out_of_sample.start} to ${cfg.periods.out_of_sample.end})`
                : ""}
              .
            </li>
          </ol>
        </Card>

        <Card title="Known limitations">
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <b>Survivorship bias.</b> The universe is the S&amp;P 100 as of September 2023,
              frozen. Names added later are missing and names that left are kept.
            </li>
            <li>
              <b>LLM lookahead through training data.</b> The extraction model was likely trained on
              data from after many of these releases, so it may know how events turned out. The
              prompt forbids using outside knowledge, but that cannot be guaranteed. This risk
              applies to every LLM backtest of historical text.
            </li>
            <li>
              <b>Model-produced evaluation labels.</b> The current evaluation set was labelled by
              Claude, not a human. It measures agreement with a stronger model, not correctness.
            </li>
            <li>
              <b>Small sample.</b> About a thousand events over under three years, clustered in a
              few weeks each quarter. Event-study t-stats assume independence and so overstate
              significance.
            </li>
            <li>
              <b>Costs and execution.</b> Fills at the adjusted open and close with a flat
              {cfg ? ` ${cfg.portfolio.cost_bps_per_side} bps` : ""} per side per leg. There is no
              slippage model, and opening auctions after earnings can be wider.
            </li>
            <li>
              <b>Beat/miss is rarely stated.</b> Releases seldom compare results with consensus, and
              outside knowledge is barred, so these labels are mostly &quot;unknown&quot; and the
              naive beat/miss baseline trades rarely.
            </li>
            <li>
              <b>Tuning.</b> Thresholds and tone weight were chosen on in-sample Sharpe from a small
              grid. Out-of-sample is the honest number, and it is still a single period.
            </li>
            <li>
              <b>Data sources.</b> Prices come from Yahoo Finance via yfinance (adjusted, free, not
              audited). Symbol changes and corporate reorganisations are mapped by hand in the
              universe file.
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
