import { api, type CloudApp } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";
import { timeAgo } from "../badges";
import { Code, Diff, Empty } from "./shared";

export function Incidents({ app }: { app: CloudApp }) {
  const { data } = usePolling(() => api.incidents(app.id), 5000);
  const incidents = data ?? [];
  if (incidents.length === 0) {
    return <Empty>No incidents. When a version fails, the analysis of its cause appears here.</Empty>;
  }
  return (
    <ol className="space-y-4">
      {incidents.map((incident) => {
        const r = incident.report;
        return (
          <li key={incident.id} className="rounded-2xl border border-danger/25 bg-danger/[0.04] p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-danger/30 bg-danger/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-danger">
                {incident.title}
              </span>
              <span className="ml-auto font-mono text-[11px] text-muted">{timeAgo(incident.created_at)}</span>
            </div>
            <p className="mt-3 font-display text-[15px] font-semibold leading-snug">{r.summary}</p>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="space-y-3 text-xs">
                {r.exception && (
                  <p><span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Error</span><br />
                    <code className="font-mono text-danger">{r.exception.type}: {r.exception.message}</code></p>
                )}
                {r.culprit && (
                  <p><span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Where</span><br />
                    <code className="font-mono">{r.culprit.file}:{r.culprit.line}</code> in <code className="font-mono">{r.culprit.function}</code>
                    {r.culprit.changed_in_this_version && <span className="text-warn"> — changed in this version</span>}</p>
                )}
                <p className="rounded-lg bg-teal/[0.07] px-3 py-2 leading-relaxed text-ink/90">
                  <span className="font-medium text-teal">How to fix · </span>{r.hint}
                </p>
                {r.suggested_fix?.current && (
                  <div>
                    <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Code at fault</p>
                    <Code>{r.suggested_fix.current}</Code>
                  </div>
                )}
              </div>
              <div className="space-y-3">
                {r.suggested_fix?.revert && (
                  <div>
                    <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
                      Suggested code: what changed (− previous, + this version)
                    </p>
                    <Diff text={r.suggested_fix.revert} />
                  </div>
                )}
                {!r.suggested_fix?.revert && r.changes[0] && (
                  <div>
                    <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Recent change</p>
                    <Diff text={r.changes[0].diff} />
                  </div>
                )}
              </div>
            </div>
            <details className="mt-3 text-xs text-muted">
              <summary className="cursor-pointer hover:text-ink">Logs used for the analysis</summary>
              <div className="mt-2"><Code>{r.log_excerpt || "No log output."}</Code></div>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
