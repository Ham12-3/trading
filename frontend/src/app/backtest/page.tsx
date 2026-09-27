import { NotBuilt } from "@/components/not-built";

export default function BacktestPage() {
  return (
    <NotBuilt
      title="Backtest"
      phase={4}
      what="Equity curve against a non-LLM baseline, drawdown and metrics, in-sample and out-of-sample."
    />
  );
}
