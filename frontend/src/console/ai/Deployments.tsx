import { useState } from "react";
import { api, type CloudApp, type Deployment } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";
import { cx } from "../../components/ui";
import { timeAgo } from "../badges";
import { Code, Empty, errorText, percent } from "./shared";

const STATUS: Record<Deployment["status"], [string, string]> = {
  running: ["in progress", "text-azure border-azure/30 bg-azure/10"],
  deployed: ["deployed", "text-teal border-teal/30 bg-teal/10"],
  promoted: ["canary promoted", "text-teal border-teal/30 bg-teal/10"],
  rolled_back: ["auto rolled back", "text-danger border-danger/30 bg-danger/10"],
  tests_failed: ["tests failed", "text-danger border-danger/30 bg-danger/10"],
  failed: ["failed", "text-danger border-danger/30 bg-danger/10"],
  blocked: ["blocked by gate", "text-warn border-warn/30 bg-warn/10"],
  manual_rollback: ["manual rollback", "text-warn border-warn/30 bg-warn/10"],
};

function Pipeline({ deployment }: { deployment: Deployment }) {
  const [open, setOpen] = useState(false);
  const p = deployment.pipeline;
  if (!p) return null;
  const changed = [...p.changed.added, ...p.changed.modified, ...p.changed.removed];
  return (
    <div className="mt-3 space-y-2 text-xs">
      {changed.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5 text-muted">
          <span className="font-mono text-[10px] uppercase tracking-[0.14em]">Changed</span>
          {changed.slice(0, 8).map((f) => (
            <code key={f} className="rounded bg-white/[0.05] px-1.5 py-0.5 font-mono text-[11px] text-ink/85">{f}</code>
          ))}
          {changed.length > 8 && <span>+{changed.length - 8}</span>}
        </p>
      )}
      <p className="text-ink/85">
        <span className={cx("font-medium", p.status === "passed" ? "text-teal" : p.status === "failed" ? "text-danger" : "text-muted")}>
          {p.status === "skipped" ? "No tests run" : `Tests ${p.status}`}
        </span>
        {p.status !== "skipped" && (
          <>
            {" "}· ran <b>{p.tests.length}</b> of {p.all_tests.length} test file(s) in {p.duration} s
            {p.mode === "impacted" && p.skipped_files ? <span className="text-teal"> · ~{p.estimated_saving} s saved</span> : null}
          </>
        )}
        <span className="text-muted"> — {p.reason}</span>
      </p>
      {p.why && Object.keys(p.why).length > 0 && (
        <ul className="space-y-0.5 font-mono text-[11px] text-muted">
          {Object.entries(p.why).map(([test, reason]) => (
            <li key={test}>▸ {test} <span className="text-ink/60">({reason})</span></li>
          ))}
        </ul>
      )}
      {p.output && (
        <button type="button" onClick={() => setOpen((v) => !v)} className="text-azure hover:underline">
          {open ? "Hide test output" : "Show test output"}
        </button>
      )}
      {open && <Code>{p.output}</Code>}
    </div>
  );
}

export function Deployments({ app }: { app: CloudApp }) {
  const { data, refresh } = usePolling(() => api.deployments(app.id), 3000);
  const [error, setError] = useState<string | null>(null);
  const deployments = data ?? [];
  const canRollBack = app.status === "running" && deployments.some((d) => d.version < (app.version ?? 0) && ["promoted", "deployed"].includes(d.status));

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted">
          Each deployment runs only the tests affected by the change, then the new version gets a small share of traffic
          and is compared with the current one before it takes over.
        </p>
        {canRollBack && (
          <button type="button" className="h-8 rounded-full border border-line px-3 text-xs text-ink/85 hover:border-warn/40"
            onClick={async () => {
              setError(null);
              try {
                await api.rollback(app.id);
              } catch (e) {
                setError(errorText(e));
              } finally {
                refresh();
              }
            }}>
            Roll back to the previous version
          </button>
        )}
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      {deployments.length === 0 ? (
        <div className="mt-4"><Empty>No deployments recorded yet.</Empty></div>
      ) : (
        <ol className="mt-5 space-y-3">
          {deployments.map((d) => {
            const [label, style] = STATUS[d.status] ?? [d.status, "text-muted border-line"];
            return (
              <li key={d.id} className={cx("rounded-xl border bg-navy-950/40 p-4", d.version === app.version && d.status !== "rolled_back" ? "border-teal/25" : "border-line")}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-display text-base font-semibold">v{d.version}</span>
                  <span className={cx("rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider", style)}>{label}</span>
                  {d.version === app.version && d.status !== "rolled_back" && <span className="font-mono text-[10px] text-teal">live</span>}
                  <span className="ml-auto font-mono text-[11px] text-muted">{timeAgo(d.created_at)}</span>
                </div>
                <Pipeline deployment={d} />
                {d.canary && (
                  <p className={cx("mt-2 text-xs", d.canary.anomalous ? "text-danger" : "text-ink/85")}>
                    Canary at {d.canary.percent}% for {d.canary.seconds} s: errors {percent(d.canary.canary.error_rate)} on v{d.version} vs{" "}
                    {percent(d.canary.stable.error_rate)} on the stable version
                    {d.canary.canary.p95 !== null && ` · p95 ${d.canary.canary.p95?.toFixed(0)} ms`}
                    {d.canary.anomalous && <> — <b>rolled back</b>: {d.canary.reason}</>}
                  </p>
                )}
                {d.detail?.error && <p className="mt-2 whitespace-pre-wrap text-xs text-danger">{d.detail.error}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
