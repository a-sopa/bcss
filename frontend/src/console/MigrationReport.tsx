import type { Effort, MigrationReport as Report } from "../lib/api";
import { cx } from "../components/ui";

const COMPATIBILITY: Record<Report["compatibility"], [string, string]> = {
  ready: ["Runs unchanged", "text-teal border-teal/30 bg-teal/10"],
  config: ["Endpoint changes only", "text-azure border-azure/30 bg-azure/10"],
  changes: ["Some code changes", "text-warn border-warn/30 bg-warn/10"],
  unsupported: ["Not supported yet", "text-danger border-danger/30 bg-danger/10"],
};

const EFFORT: Record<Effort, [string, string]> = {
  none: ["built in", "text-teal"],
  config: ["endpoint only", "text-azure"],
  code: ["code change", "text-warn"],
};

/** Migration report; `env` may be values (before deploying) or just names (stored on an app). */
export function MigrationReport({ report, compact = false }: { report: Report<Record<string, string> | string[]>; compact?: boolean }) {
  const [label, style] = COMPATIBILITY[report.compatibility];
  const envCount = Array.isArray(report.env) ? report.env.length : Object.keys(report.env).length;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-display text-[15px] font-semibold">{report.platform}</p>
          <span className={cx("rounded-full border px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", style)}>
            {label}
          </span>
        </div>
        {report.runtime_label && <p className="mt-1 font-mono text-[11px] text-muted">{report.runtime_label}</p>}
        {report.error && <p className="mt-2 text-xs text-danger">{report.error}</p>}
      </div>

      {report.access_keys.length > 0 && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
          <p className="font-medium">Hard-coded AWS access key{report.access_keys.length > 1 ? "s" : ""} found</p>
          <ul className="mt-1 font-mono text-[11px]">
            {report.access_keys.map((k) => (
              <li key={`${k.file}:${k.line}`}>
                {k.key} · {k.file}:{k.line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.services.length > 0 && (
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">AWS services → open source</p>
          <ul className={cx("mt-2 divide-y divide-line border-y border-line", !compact && "sm:grid sm:grid-cols-2 sm:gap-x-6 sm:divide-y-0 sm:border-0")}>
            {report.services.map((s) => (
              <li key={s.id} className={cx("py-2.5", !compact && "sm:border-t sm:border-line")}>
                <p className="text-[13px]">
                  <span className="text-muted">{s.aws}</span> <span className="text-muted/60">→</span>{" "}
                  <span className="font-medium">{s.replacement}</span>
                </p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-muted">
                  <span className={cx("font-mono", EFFORT[s.effort][1])}>{EFFORT[s.effort][0]}</span> · {s.how}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.services.length === 0 && !report.error && (
        <p className="text-xs text-muted">No AWS SDK calls found — nothing to replace.</p>
      )}

      {report.notes.length > 0 && (
        <ul className="space-y-1.5">
          {report.notes.map((note) => (
            <li key={note} className="flex gap-2 text-xs leading-relaxed text-muted">
              <span className="mt-1.5 size-1 shrink-0 rounded-full bg-teal/70" aria-hidden="true" />
              {note}
            </li>
          ))}
        </ul>
      )}

      {compact || envCount === 0 ? null : (
        <p className="font-mono text-[11px] text-muted">
          Environment: {Array.isArray(report.env) ? report.env.join(", ") : Object.keys(report.env).join(", ")}
        </p>
      )}
    </div>
  );
}
