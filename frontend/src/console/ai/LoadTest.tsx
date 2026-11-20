import { useState } from "react";
import { api, type CloudApp } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";
import { cx } from "../../components/ui";
import { timeAgo } from "../badges";
import { Empty, errorText, percent, Stat } from "./shared";

export function LoadTest({ app }: { app: CloudApp }) {
  const model = usePolling(() => api.loadModel(app.id), 6000);
  const tests = usePolling(() => api.loadTests(app.id), 3000);
  const [users, setUsers] = useState(50);
  const [error, setError] = useState<string | null>(null);
  const learned = model.data;
  const running = (tests.data ?? []).some((t) => t.status === "running");
  const latest = tests.data?.[0];

  const start = async () => {
    setError(null);
    try {
      await api.startLoadTest(app.id, users);
      tests.refresh();
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <div className="space-y-6">
      <section>
        <h3 className="font-display text-sm font-semibold">Traffic learned from real visitors</h3>
        {!learned || learned.requests === 0 ? (
          <div className="mt-2"><Empty>No real traffic yet. Open the app and browse it: the load test copies how people really use it.</Empty></div>
        ) : (
          <>
            <div className="mt-3 grid gap-3 sm:grid-cols-4">
              <Stat label="Requests observed" value={learned.requests} />
              <Stat label="Sessions" value={learned.sessions} />
              <Stat label="Think time" value={`${learned.think_time_s} s`} />
              <Stat label="Peak" value={`${learned.peak_rps} req/s`} />
            </div>
            <ul className="mt-3 grid gap-x-6 gap-y-1 font-mono text-xs sm:grid-cols-2">
              {learned.paths.slice(0, 8).map((p) => (
                <li key={p.path} className="flex justify-between gap-3"><span className="truncate">{p.path}</span>
                  <span className="text-muted">{percent(p.count / learned.requests)}</span></li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">
          <span className="font-mono text-[10px] uppercase tracking-[0.14em]">Up to virtual users</span>
          <select value={users} onChange={(e) => setUsers(Number(e.target.value))}
            className="mt-1 block h-9 rounded-lg border border-line bg-navy-950/70 px-3 text-sm text-ink">
            {[10, 20, 50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button type="button" disabled={running || !learned?.requests} onClick={start}
          className="h-9 rounded-full bg-teal px-5 text-xs font-medium text-navy-950 hover:bg-teal-soft disabled:opacity-40">
          {running ? "Running…" : "Run load test"}
        </button>
        {learned?.requests ? (
          <a href={api.k6Url(app.id, users)} download className="h-9 rounded-full border border-line px-4 text-xs leading-9 text-ink/85 hover:border-teal/40">
            Download k6 script
          </a>
        ) : null}
        {error && <p className="w-full text-xs text-danger">{error}</p>}
      </section>

      {latest && (
        <section className="rounded-xl border border-line bg-navy-950/40 p-4">
          <div className="flex items-center gap-2">
            <h3 className="font-display text-sm font-semibold">Latest load test</h3>
            <span className="ml-auto font-mono text-[11px] text-muted">{timeAgo(latest.created_at)}</span>
          </div>
          {latest.status === "running" && <p className="mt-2 text-xs text-azure">Running {latest.plan?.stages.length} stages…</p>}
          {latest.result?.error && <p className="mt-2 text-xs text-danger">{latest.result.error}</p>}
          {latest.result?.verdict && <p className="mt-2 text-sm font-medium">{latest.result.verdict}</p>}
          {latest.result?.stages && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-sm">
                <thead>
                  <tr className="border-b border-line font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
                    <th className="py-2 pr-4 font-normal">Users</th><th className="py-2 pr-4 font-normal">Req/s</th>
                    <th className="py-2 pr-4 font-normal">p50</th><th className="py-2 pr-4 font-normal">p95</th><th className="py-2 font-normal">Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {latest.result.stages.map((s) => {
                    const broken = (s.p95_ms ?? 0) > 1000 || s.error_rate > 0.01;
                    return (
                      <tr key={s.users} className={cx("border-b border-line/60 last:border-0", broken && "text-danger")}>
                        <td className="py-2 pr-4 font-mono text-xs">{s.users}</td>
                        <td className="py-2 pr-4 font-mono text-xs">{s.rps}</td>
                        <td className="py-2 pr-4 font-mono text-xs">{s.p50_ms ?? "—"} ms</td>
                        <td className="py-2 pr-4 font-mono text-xs">{s.p95_ms ?? "—"} ms</td>
                        <td className="py-2 font-mono text-xs">{percent(s.error_rate, 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
