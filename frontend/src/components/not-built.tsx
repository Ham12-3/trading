/** Honest placeholder for pages whose data pipeline has not been built yet. */
export function NotBuilt({ title, phase, what }: { title: string; phase: number; what: string }) {
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-muted max-w-prose">{what}</p>
      <p className="text-muted text-sm">
        Not built yet. This page gets real data in Phase {phase}.
      </p>
    </section>
  );
}
