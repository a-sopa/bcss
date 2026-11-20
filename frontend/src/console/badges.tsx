import type { AppStatus, CloudEvent, ScanSummary, Tier } from "../lib/api";
import { cx } from "../components/ui";

const BUSY: AppStatus[] = ["queued", "scanning", "building", "starting", "restarting"];

const STATUS_STYLE: Record<AppStatus, string> = {
  running: "text-teal border-teal/30 bg-teal/10",
  queued: "text-azure border-azure/30 bg-azure/10",
  scanning: "text-azure border-azure/30 bg-azure/10",
  building: "text-azure border-azure/30 bg-azure/10",
  starting: "text-azure border-azure/30 bg-azure/10",
  restarting: "text-warn border-warn/30 bg-warn/10",
  stopped: "text-muted border-line bg-white/[0.03]",
  missing: "text-muted border-line bg-white/[0.03]",
  blocked: "text-warn border-warn/30 bg-warn/10",
  crashed: "text-danger border-danger/30 bg-danger/10",
  failed: "text-danger border-danger/30 bg-danger/10",
};

export function StatusPill({ status }: { status: AppStatus }) {
  const busy = BUSY.includes(status);
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] tracking-wide",
        STATUS_STYLE[status],
      )}
    >
      <span className={cx("size-1.5 rounded-full bg-current", busy && "animate-pulse")} aria-hidden="true" />
      {status}
    </span>
  );
}

export const TIER_STYLE: Record<Tier, string> = {
  critical: "text-danger border-danger/30 bg-danger/10",
  medium: "text-warn border-warn/30 bg-warn/10",
  resilient: "text-teal border-teal/30 bg-teal/10",
  unknown: "text-muted border-line bg-white/[0.03]",
};

export function TierPill({ tier }: { tier: Tier }) {
  return (
    <span className={cx("inline-flex rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider", TIER_STYLE[tier])}>
      {tier}
    </span>
  );
}

export function QuantumBadge({ summary }: { summary: ScanSummary | null }) {
  if (!summary) return <span className="font-mono text-[11px] text-muted">—</span>;
  const base = "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px]";
  if (summary.status === "unavailable") return <span className={cx(base, TIER_STYLE.unknown)}>scan unavailable</span>;
  if (summary.status === "skipped") return <span className={cx(base, TIER_STYLE.unknown)}>not scanned</span>;
  const tiers = summary.tiers!;
  if (tiers.critical) return <span className={cx(base, TIER_STYLE.critical)}>{tiers.critical} critical</span>;
  if (tiers.medium) return <span className={cx(base, TIER_STYLE.medium)}>{tiers.medium} medium</span>;
  return <span className={cx(base, TIER_STYLE.resilient)}>no vulnerable crypto</span>;
}

const SEVERITY_DOT: Record<CloudEvent["severity"], string> = {
  info: "bg-teal/70",
  low: "bg-azure",
  medium: "bg-warn",
  high: "bg-danger",
  critical: "bg-danger",
};

export function SeverityDot({ severity }: { severity: CloudEvent["severity"] }) {
  return <span className={cx("mt-1.5 size-1.5 shrink-0 rounded-full", SEVERITY_DOT[severity])} aria-label={severity} />;
}

export function timeAgo(ts: number) {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
