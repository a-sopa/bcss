import { useState } from "react";
import { api, type CloudApp } from "../lib/api";
import { usePolling } from "../hooks/usePolling";
import { cx } from "../components/ui";
import { SeverityDot, TierPill, TIER_STYLE, timeAgo } from "./badges";
import { MigrationReport } from "./MigrationReport";

type Tab = "quantum" | "migration" | "logs" | "activity";

function QuantumTab({ app }: { app: CloudApp }) {
  const summary = app.scan_summary;
  if (!summary) return <p className="text-sm text-muted">The analysis will appear here once the scan has run.</p>;
  if (summary.status === "skipped" || summary.status === "unavailable") {
    return <p className="text-sm text-muted">{summary.reason}</p>;
  }
  const tiers = summary.tiers!;
  const findings = summary.top ?? [];

  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-10 gap-y-5">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">Quantum exposure</p>
          <p className="mt-1 font-display text-4xl font-semibold tracking-[-0.03em]">
            {summary.score ?? "—"}
            <span className="ml-1 text-base font-medium text-muted">/ 100</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(["critical", "medium", "resilient", "unknown"] as const).map((tier) => (
            <span key={tier} className={cx("rounded-lg border px-3 py-1.5 font-mono text-xs", TIER_STYLE[tier])}>
              {tiers[tier]} {tier}
            </span>
          ))}
        </div>
        <p className="text-xs text-muted">
          {summary.files_scanned} file(s) analysed by QuantumTrace · higher score means more exposure
        </p>
      </div>

      {findings.length > 0 && (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-line font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
                <th className="py-2 pr-4 font-normal">Tier</th>
                <th className="py-2 pr-4 font-normal">Algorithm</th>
                <th className="py-2 pr-4 font-normal">Location</th>
                <th className="py-2 font-normal">Recommendation</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((f, i) => (
                <tr key={i} className="border-b border-line/60 align-top last:border-0">
                  <td className="py-3 pr-4">
                    <TierPill tier={f.tier} />
                  </td>
                  <td className="py-3 pr-4">
                    <span className="font-medium">{f.algorithm}</span>
                    <span className="block text-xs text-muted">{f.usage.replace("_", " ")}</span>
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-ink/80">
                    {f.file}
                    <span className="block text-muted">{f.locator}</span>
                  </td>
                  <td className="py-3 text-xs leading-relaxed text-muted" title={f.rationale ?? undefined}>
                    {f.recommendation}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LogsTab({ app }: { app: CloudApp }) {
  const { data } = usePolling(() => api.logs(app.id), 3000);
  return (
    <pre className="max-h-80 overflow-auto rounded-xl border border-line bg-navy-950/80 p-4 font-mono text-xs leading-relaxed text-ink/80">
      {data?.logs.trim() || "No output yet."}
    </pre>
  );
}

function ActivityTab({ app }: { app: CloudApp }) {
  const { data } = usePolling(() => api.events(app.id), 3000);
  return (
    <ul className="space-y-3">
      {(data ?? []).map((e) => (
        <li key={e.id} className="flex gap-3 text-sm">
          <SeverityDot severity={e.severity} />
          <div className="min-w-0">
            <p>
              {e.title} <span className="font-mono text-[11px] text-muted">· {e.module} · {timeAgo(e.ts)}</span>
            </p>
            {e.detail && <p className="mt-0.5 text-xs break-words whitespace-pre-wrap text-muted">{e.detail}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function StatsLine({ app }: { app: CloudApp }) {
  const { data } = usePolling(() => api.stats(app.id), 4000, app.status === "running");
  if (app.status !== "running" || !data) return null;
  const mb = (bytes: number) => (bytes / 1024 / 1024).toFixed(0);
  return (
    <p className="font-mono text-[11px] text-muted">
      CPU {data.cpu_percent.toFixed(1)}% · Memory {mb(data.memory_bytes)} / {mb(data.memory_limit_bytes)} MB
    </p>
  );
}

export function AppDetail({ app }: { app: CloudApp }) {
  const migrated = app.migration?.platform.startsWith("AWS") ?? false;
  const [tab, setTab] = useState<Tab>(migrated ? "migration" : "quantum");
  const tabs: [Tab, string][] = [
    ...(migrated ? [["migration", "Migration"] as [Tab, string]] : []),
    ["quantum", "Quantum analysis"],
    ["logs", "Logs"],
    ["activity", "Activity"],
  ];

  return (
    <div className="border-t border-line px-5 pt-4 pb-6 sm:px-6">
      {app.detail && (
        <p
          className={cx(
            "mb-4 rounded-lg border px-3 py-2 text-xs whitespace-pre-wrap",
            app.status === "failed" ? "border-danger/30 bg-danger/10 text-danger" : app.status === "blocked" ? "border-warn/30 bg-warn/10 text-warn" : "border-line text-muted",
          )}
        >
          {app.detail}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" className="flex gap-1 rounded-full border border-line p-1">
          {tabs.map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={cx(
                "rounded-full px-3.5 py-1.5 text-xs transition-colors duration-300",
                tab === id ? "bg-white/[0.08] text-ink" : "text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <StatsLine app={app} />
      </div>
      <div className="mt-5">
        {tab === "migration" && app.migration && <MigrationReport report={app.migration} />}
        {tab === "quantum" && <QuantumTab app={app} />}
        {tab === "logs" && <LogsTab app={app} />}
        {tab === "activity" && <ActivityTab app={app} />}
      </div>
    </div>
  );
}
