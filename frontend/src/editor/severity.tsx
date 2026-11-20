import type { Severity } from "../lib/api";
import { cx } from "../components/ui";

/** The editor's colour scale: yellow → orange → red → black. */
export const SEVERITY_META: Record<Severity, { label: string; meaning: string; color: string }> = {
  low: { label: "Low", meaning: "Minor weakness", color: "#F2C94C" },
  medium: { label: "Medium", meaning: "Weak", color: "#FF9F43" },
  high: { label: "High", meaning: "Vulnerable", color: "#FF4D5E" },
  critical: { label: "Critical", meaning: "Severely vulnerable", color: "#000000" },
};

export function SeveritySwatch({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "inline-block size-2.5 shrink-0 rounded-full",
        severity === "critical" && "ring-1 ring-white/80",
        className,
      )}
      style={{ background: SEVERITY_META[severity].color }}
    />
  );
}

export function SeverityPill({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        severity === "critical" ? "border-white/40 bg-black text-white" : "border-current/30",
      )}
      style={severity === "critical" ? undefined : { color: meta.color, background: `${meta.color}1A` }}
    >
      {meta.label}
    </span>
  );
}
