import { useState } from "react";
import type { CodeFinding } from "../lib/api";
import { cx } from "../components/ui";
import { SEVERITY_META, SeverityPill } from "./severity";

type Props = {
  findings: CodeFinding[];
  openPath: string | null;
  stale: boolean;
  onGoTo: (finding: CodeFinding) => void;
  onApply: (finding: CodeFinding) => void;
};

export function FindingsPanel({ findings, openPath, stale, onGoTo, onApply }: Props) {
  const [scope, setScope] = useState<"file" | "all">("file");
  const visible = scope === "file" ? findings.filter((f) => f.file === openPath) : findings;

  return (
    <aside aria-label="Findings" className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">Findings</h2>
        <div role="tablist" className="flex gap-0.5 rounded-full border border-line p-0.5">
          {(
            [
              ["file", "This file"],
              ["all", "All files"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={scope === id}
              onClick={() => setScope(id)}
              className={cx(
                "rounded-full px-2.5 py-1 text-[11px] transition-colors",
                scope === id ? "bg-white/[0.08] text-ink" : "text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <ul className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        {visible.length === 0 && (
          <li className="px-2 py-8 text-center text-sm text-muted">
            {scope === "file" ? "No issues in this file." : "No issues found."}
          </li>
        )}
        {visible.map((f) => (
          <li
            key={f.id}
            className="rounded-xl border border-line bg-navy-950/40 p-3"
            style={{ borderLeft: `3px solid ${f.severity === "critical" ? "#ffffff" : SEVERITY_META[f.severity].color}` }}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-[13px] font-medium leading-snug">{f.title}</p>
              <SeverityPill severity={f.severity} />
            </div>
            <button
              type="button"
              onClick={() => onGoTo(f)}
              className="mt-1 font-mono text-[11px] text-azure hover:underline"
            >
              {f.file}:{f.line}
            </button>
            <span className="ml-2 font-mono text-[10px] text-muted">
              {f.source === "quantum" ? "QuantumTrace" : f.rule}
              {f.cwe ? ` · ${f.cwe}` : ""}
            </span>
            <p className="mt-2 text-xs leading-relaxed text-muted">{f.message}</p>
            {f.suggestion && (
              <p className="mt-2 rounded-lg bg-teal/[0.06] px-2.5 py-2 text-xs leading-relaxed text-ink/85">
                <span className="font-medium text-teal">Suggestion · </span>
                {f.suggestion}
              </p>
            )}
            {f.fix && (
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  disabled={stale}
                  onClick={() => onApply(f)}
                  className="h-7 rounded-full bg-teal/15 px-3 text-xs text-teal transition-colors hover:bg-teal/25 disabled:opacity-40"
                >
                  Apply fix
                </button>
                <code className="truncate font-mono text-[11px] text-muted" title={f.fix.text}>
                  → {f.fix.text.trim()}
                </code>
              </div>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}
