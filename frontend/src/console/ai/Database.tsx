import { useState } from "react";
import { api, type CloudApp, type DbAction } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";
import { cx } from "../../components/ui";
import { timeAgo } from "../badges";
import { Empty, errorText, Stat } from "./shared";

const ACTION: Record<DbAction["kind"], [string, string]> = {
  index_created: ["index created", "text-teal"],
  index_rejected: ["index tried, not kept", "text-muted"],
  index_dropped: ["unused index dropped", "text-warn"],
  index_failed: ["index failed", "text-danger"],
  suggestion: ["rewrite suggested", "text-azure"],
};

export function Database({ app }: { app: CloudApp }) {
  const { data, refresh } = usePolling(() => api.database(app.id), 5000);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = (action: () => Promise<unknown>, done: string) => async () => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage(done);
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setBusy(false);
      refresh();
    }
  };

  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  if (!data.enabled) {
    return (
      <div className="rounded-2xl border border-line bg-navy-950/40 p-6">
        <h3 className="font-display text-base font-semibold">Managed PostgreSQL with autonomous tuning</h3>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Adds a private PostgreSQL 16 database for this app (available as <code className="font-mono text-ink/85">DATABASE_URL</code>).
          OwnCloud then watches the slowest queries, creates the indexes they need — keeping them only when the planner
          uses them and they cut the cost — drops its unused indexes, and suggests query rewrites.
        </p>
        <button type="button" disabled={busy} onClick={run(() => api.enableDatabase(app.id), "Database created; the app is redeploying.")}
          className="mt-5 h-10 rounded-full bg-teal px-5 text-sm font-medium text-navy-950 hover:bg-teal-soft disabled:opacity-40">
          {busy ? "Creating…" : "Add a database"}
        </button>
        {message && <p className="mt-3 text-xs text-muted">{message}</p>}
      </div>
    );
  }

  const actions = data.actions ?? [];
  const created = actions.filter((a) => a.kind === "index_created");
  const suggestions = actions.filter((a) => a.kind === "suggestion");
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="grid flex-1 gap-3 sm:grid-cols-3">
          <Stat label="Database" value={data.running ? "running" : "stopped"} tone={data.running ? "good" : "bad"} />
          <Stat label="Indexes created" value={created.length} tone="good" />
          <Stat label="Rewrite suggestions" value={suggestions.length} />
        </div>
        <button type="button" disabled={busy} onClick={run(() => api.optimiseDatabase(app.id), "Optimisation pass finished.")}
          className="h-9 rounded-full border border-line px-4 text-xs text-ink/85 hover:border-teal/40 disabled:opacity-40">
          {busy ? "Optimising…" : "Optimise now"}
        </button>
      </div>
      {message && <p className="text-xs text-muted">{message}</p>}

      <section>
        <h3 className="font-display text-sm font-semibold">Slowest queries</h3>
        {(data.slow_queries ?? []).length === 0 ? (
          <div className="mt-2"><Empty>No queries recorded yet.</Empty></div>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b border-line font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
                  <th className="py-2 pr-4 font-normal">Mean</th><th className="py-2 pr-4 font-normal">Calls</th><th className="py-2 font-normal">Query</th>
                </tr>
              </thead>
              <tbody>
                {data.slow_queries!.slice(0, 8).map((q) => (
                  <tr key={q.id} className="border-b border-line/60 align-top last:border-0">
                    <td className={cx("py-2 pr-4 font-mono text-xs", q.mean_ms >= 10 ? "text-warn" : "text-ink/80")}>{q.mean_ms} ms</td>
                    <td className="py-2 pr-4 font-mono text-xs">{q.calls}</td>
                    <td className="py-2 font-mono text-[11px] text-ink/80"><span className="line-clamp-2">{q.query}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h3 className="font-display text-sm font-semibold">What the optimiser did</h3>
        {actions.length === 0 ? (
          <div className="mt-2"><Empty>Nothing yet: the optimiser runs every 30 seconds once queries are slow.</Empty></div>
        ) : (
          <ul className="mt-2 space-y-2">
            {actions.slice(0, 20).map((a) => {
              const [label, tone] = ACTION[a.kind];
              return (
                <li key={a.id} className="rounded-xl border border-line bg-navy-950/40 p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cx("font-medium", tone)}>{label}</span>
                    {a.kind === "index_created" && (
                      <span className="text-ink/85">
                        cost {Number(a.detail.cost_before).toFixed(0)} → {Number(a.detail.cost_after).toFixed(1)}
                        {a.detail.mean_ms_now !== undefined && <> · {a.detail.mean_ms_before} ms → <b className="text-teal">{a.detail.mean_ms_now} ms</b></>}
                      </span>
                    )}
                    <span className="ml-auto font-mono text-[11px] text-muted">{timeAgo(a.created_at)}</span>
                  </div>
                  {a.kind === "suggestion" ? (
                    <p className="mt-1.5 leading-relaxed text-ink/85">{a.detail.advice}</p>
                  ) : (
                    <code className="mt-1.5 block break-all font-mono text-[11px] text-ink/80">{a.statement}</code>
                  )}
                  {a.detail.query && <code className="mt-1 block truncate font-mono text-[11px] text-muted">{a.detail.query}</code>}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
