import { api, type CloudApp } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";
import { CANARY, DANGER, Empty, Sparkline, STABLE, Stat, percent } from "./shared";

export function Traffic({ app }: { app: CloudApp }) {
  const { data } = usePolling(() => api.traffic(app.id), 4000);
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  if (!data.available) return <Empty>Traffic appears here once the app runs behind its router (redeploy older apps once).</Empty>;

  const versions = Object.entries(data.versions).filter(([, v]) => v.weight > 0 || v.series.some((p) => p.rps > 0)).slice(-3);
  const color = (role: string | null) => (role === "canary" ? CANARY : STABLE);
  const regions = Object.entries(data.cache.regions).sort((a, b) => (b[1].visitors ?? 0) - (a[1].visitors ?? 0));
  const edgeShare = data.cache.requests ? data.cache.served_from_edge / data.cache.requests : null;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-4">
        {versions.map(([name, v]) => (
          <Stat key={name} label={`${name} · ${v.role ?? "retired"}`} value={`${v.weight}%`} tone={v.role === "canary" ? "warn" : "good"} />
        ))}
        <Stat label="Served from the edge" value={percent(edgeShare)} tone="good" />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Sparkline label="Requests / s" series={versions.map(([n, v]) => ({ name: n, color: color(v.role), values: v.series.map((p) => p.rps) }))} />
        <Sparkline label="Errors" format={(x) => percent(x)}
          series={versions.map(([n, v]) => ({ name: n, color: v.role === "canary" ? CANARY : DANGER, values: v.series.map((p) => (p.rps ? p.error_rate : null)) }))} />
        <Sparkline label="p95 latency (ms)" format={(x) => x.toFixed(0)}
          series={versions.map(([n, v]) => ({ name: n, color: color(v.role), values: v.series.map((p) => p.p95) }))} />
      </div>

      <section>
        <h3 className="font-display text-sm font-semibold">Edge cache by region</h3>
        <p className="mt-1 text-xs text-muted">
          Anonymous, cacheable responses are kept per region. Pages that visitors of a region usually open next are fetched ahead of time.
        </p>
        {regions.length === 0 ? (
          <div className="mt-3"><Empty>No visitors yet.</Empty></div>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className="border-b border-line font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
                  <th className="py-2 pr-4 font-normal">Region</th><th className="py-2 pr-4 font-normal">Visitors</th>
                  <th className="py-2 pr-4 font-normal">Hit rate</th><th className="py-2 pr-4 font-normal">Cached</th>
                  <th className="py-2 font-normal">Prefetched → used</th>
                </tr>
              </thead>
              <tbody>
                {regions.map(([region, r]) => (
                  <tr key={region} className="border-b border-line/60 last:border-0">
                    <td className="py-2 pr-4 capitalize">{region}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{r.visitors}</td>
                    <td className="py-2 pr-4">
                      <span className="inline-flex items-center gap-2">
                        <span className="h-1.5 w-20 overflow-hidden rounded-full bg-white/[0.06]">
                          <span className="block h-full rounded-full bg-teal" style={{ width: `${(r.hit_rate ?? 0) * 100}%` }} />
                        </span>
                        <span className="font-mono text-xs">{percent(r.hit_rate)}</span>
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs">{r.entries}</td>
                    <td className="py-2 font-mono text-xs">{r.prefetched ?? 0} → {r.prefetch_hits ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section>
          <h3 className="font-display text-sm font-semibold">Most visited</h3>
          <ul className="mt-2 space-y-1 font-mono text-xs">
            {data.top_paths.map((p) => (
              <li key={p.path} className="flex justify-between gap-3"><span className="truncate">{p.path}</span><span className="text-muted">{p.count}</span></li>
            ))}
          </ul>
        </section>
        <section>
          <h3 className="font-display text-sm font-semibold">Learned navigation (used for prefetching)</h3>
          <ul className="mt-2 space-y-1 font-mono text-xs">
            {data.predictions.slice(0, 8).map((p, i) => (
              <li key={i} className="flex justify-between gap-3">
                <span className="truncate">{p.from} <span className="text-teal">→</span> {p.to}</span>
                <span className="text-muted">{p.region} · {p.count}</span>
              </li>
            ))}
            {data.predictions.length === 0 && <li className="text-muted">Not enough navigation yet.</li>}
          </ul>
        </section>
      </div>
    </div>
  );
}
