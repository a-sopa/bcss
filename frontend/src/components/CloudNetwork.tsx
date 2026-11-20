import { useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CLOUD_CENTER, LOGO_TRANSFORM, TITLE_Y, VIEW, buildTraces, type Trace } from "../lib/traces";
import { LOGO_PATHS } from "../lib/logo";

const LINE = "#6FE4D6";
const EASE = [0.22, 1, 0.36, 1] as const;
const TRACE_EASE = [0.5, 0, 0.25, 1] as const;

// Intro sequence (seconds): logo fades in → traces grow outward → live pulses.
export const T = { cloud: 0.1, traces: 1.3, draw: 2.8, pulses: 5.4 };

function TraceLine({ t, still }: { t: Trace; still: boolean }) {
  const delay = T.traces + t.delay;
  // Each pulse gets its own start and pace, so the glows drift apart and never sync up.
  const [pulse] = useState(() => ({ delay: T.pulses + Math.random() * 9, duration: 5 + Math.random() * 7 }));

  return (
    <g>
      <motion.path
        d={t.d}
        fill="none"
        stroke={LINE}
        strokeWidth={t.main ? 1.1 : 0.8}
        strokeLinecap="round"
        initial={still ? false : { pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: t.main ? 0.95 : 0.6 }}
        transition={{
          pathLength: { delay, duration: T.draw, ease: TRACE_EASE },
          opacity: { delay, duration: 0.01 },
        }}
      />

      {!still && (
        <path
          className="net-pulse"
          d={t.d}
          pathLength={1}
          fill="none"
          stroke="#E6FFFB"
          strokeWidth={t.main ? 1.6 : 1.2}
          strokeLinecap="round"
          style={{ animationDelay: `${pulse.delay}s`, animationDuration: `${pulse.duration}s` }}
        />
      )}
    </g>
  );
}

export function CloudNetwork({ className }: { className?: string }) {
  const traces = useMemo(() => buildTraces(), []);
  const still = useReducedMotion() ?? false;

  return (
    <svg
      className={className}
      viewBox={`${-VIEW.w / 2} ${-VIEW.h / 2} ${VIEW.w} ${VIEW.h}`}
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label="The BCSS logo, with connections radiating out in every direction."
    >
      <defs>
        <filter id="trace-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="cloud-bloom" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="40" />
        </filter>
        <linearGradient id="cloud-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="0.6" stopColor="#E8F1FF" />
          <stop offset="1" stopColor="#B4CEFF" />
        </linearGradient>
        {/* Traces fade out behind the logo and the title instead of running through them. */}
        <radialGradient id="title-hole" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0.6" stopColor="#000" />
          <stop offset="1" stopColor="#fff" />
        </radialGradient>
        <mask id="title-mask" maskUnits="userSpaceOnUse" x={-VIEW.w / 2} y={-VIEW.h / 2} width={VIEW.w} height={VIEW.h}>
          <rect x={-VIEW.w / 2} y={-VIEW.h / 2} width={VIEW.w} height={VIEW.h} fill="#fff" />
          <ellipse cx={CLOUD_CENTER.x} cy={CLOUD_CENTER.y} rx="150" ry="92" fill="url(#title-hole)" />
          <ellipse cx="0" cy={TITLE_Y + 50} rx="400" ry="85" fill="url(#title-hole)" />
        </mask>
      </defs>

      <g mask="url(#title-mask)" filter="url(#trace-glow)">
        {traces.map((t) => (
          <TraceLine key={t.id} t={t} still={still} />
        ))}
      </g>

      <motion.ellipse
        cx={CLOUD_CENTER.x}
        cy={CLOUD_CENTER.y}
        rx="120"
        ry="70"
        fill="#38BDF8"
        filter="url(#cloud-bloom)"
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 0.3 }}
        transition={{ delay: T.cloud + 0.4, duration: 2, ease: EASE }}
      />

      <motion.g
        transform={LOGO_TRANSFORM}
        fill="url(#cloud-fill)"
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: T.cloud, duration: 1.3, ease: EASE }}
      >
        {LOGO_PATHS.map((d) => (
          <path key={d.slice(0, 24)} d={d} />
        ))}
      </motion.g>
    </svg>
  );
}
