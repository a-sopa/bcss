import type { ReactNode } from "react";
import { cx } from "../../components/ui";

export const STABLE = "#42D6C5";
export const CANARY = "#528BFF";
export const DANGER = "#FF7A8A";

/** A small line chart (several series share the y scale). */
export function Sparkline({
  series,
  height = 56,
  format = (v: number) => v.toFixed(1),
  label,
}: {
  series: { name: string; color: string; values: (number | null)[] }[];
  height?: number;
  format?: (value: number) => string;
  label: string;
}) {
  const width = 300;
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const max = Math.max(1e-9, ...all);
  const length = Math.max(2, ...series.map((s) => s.values.length));
  const point = (v: number, i: number) => `${(i / (length - 1)) * width},${height - 4 - (v / max) * (height - 8)}`;
  const latest = series.map((s) => [...s.values].reverse().find((v) => v !== null) ?? null);
  return (
    <figure className="min-w-0">
      <figcaption className="flex items-baseline justify-between gap-2 text-[11px] text-muted">
        <span className="font-mono uppercase tracking-[0.14em]">{label}</span>
        <span className="flex gap-3 font-mono">
          {series.map((s, i) => (
            <span key={s.name} style={{ color: s.color }}>
              {s.name} {latest[i] === null ? "—" : format(latest[i]!)}
            </span>
          ))}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="mt-1.5 h-14 w-full" role="img" aria-label={label}>
        <line x1="0" x2={width} y1={height - 4} y2={height - 4} stroke="rgb(160 190 220 / 0.12)" />
        {series.map((s) => {
          const segments: string[][] = [[]];
          s.values.forEach((v, i) => (v === null ? segments.push([]) : segments[segments.length - 1].push(point(v, i))));
          return segments
            .filter((seg) => seg.length > 1)
            .map((seg, i) => (
              <polyline key={`${s.name}-${i}`} points={seg.join(" ")} fill="none" stroke={s.color} strokeWidth="1.6"
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            ));
        })}
      </svg>
    </figure>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className="rounded-xl border border-line bg-navy-950/40 px-4 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">{label}</p>
      <p className={cx("mt-1 font-display text-xl font-semibold tracking-[-0.02em]",
        tone === "good" && "text-teal", tone === "bad" && "text-danger", tone === "warn" && "text-warn")}>
        {value}
      </p>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-sm text-muted">{children}</p>;
}

export function Code({ children }: { children: string }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-xl border border-line bg-navy-950/80 p-3 font-mono text-[11px] leading-relaxed text-ink/85">
      {children}
    </pre>
  );
}

export function Diff({ text }: { text: string }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-xl border border-line bg-navy-950/80 p-3 font-mono text-[11px] leading-relaxed">
      {text.split("\n").map((line, i) => (
        <span key={i} className={cx("block",
          line.startsWith("+") && !line.startsWith("+++") && "bg-teal/10 text-teal",
          line.startsWith("-") && !line.startsWith("---") && "bg-danger/10 text-danger",
          line.startsWith("@@") && "text-azure")}>
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

export const percent = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`);
export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
