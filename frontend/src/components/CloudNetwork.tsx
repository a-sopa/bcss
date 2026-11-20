import { useMemo } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useLayout } from "../hooks/useLayout";
import {
  CLOUD_CENTER,
  CLOUD_PATH,
  LAYOUTS,
  NODE_RADIUS,
  buildConnections,
  type Connection,
  type Tone,
} from "../lib/network";

const TEAL = "#42D6C5";
const AZURE = "#528BFF";
const EASE = [0.22, 1, 0.36, 1] as const;

// Intro sequence (seconds): cloud → paths from their endpoints → nodes → glow → live pulses.
const T = { cloud: 0, paths: 0.55, nodes: 1.35, glow: 2.1, pulses: 3.4 };

const endColor = (tone: Tone) => (tone === "azure" ? AZURE : TEAL);
const startColor = (tone: Tone) => (tone === "teal" ? TEAL : AZURE);

/** Directional gradient: invisible at the cloud, brightest at the node. */
function PathGradient({ c }: { c: Connection }) {
  return (
    <linearGradient
      id={`grad-${c.id}`}
      gradientUnits="userSpaceOnUse"
      x1={c.origin.x}
      y1={c.origin.y}
      x2={c.node.x}
      y2={c.node.y}
    >
      <stop offset="0" stopColor={startColor(c.tone)} stopOpacity="0" />
      <stop offset="0.22" stopColor={startColor(c.tone)} stopOpacity="0.06" />
      <stop offset="0.55" stopColor={endColor(c.tone)} stopOpacity="0.38" />
      <stop offset="0.85" stopColor={endColor(c.tone)} stopOpacity="0.8" />
      <stop offset="1" stopColor={endColor(c.tone)} stopOpacity="0.95" />
    </linearGradient>
  );
}

function Node({ c, index, labelSize, still }: { c: Connection; index: number; labelSize: number; still: boolean }) {
  const color = endColor(c.tone);
  const labelX = c.align === "start" ? -NODE_RADIUS : c.align === "end" ? NODE_RADIUS : 0;
  const labelY = c.side === "top" ? -NODE_RADIUS - 18 : NODE_RADIUS + 18 + labelSize * 0.7;

  return (
    <motion.g
      className="net-node"
      tabIndex={0}
      role="img"
      aria-label={c.label}
      initial={still ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: T.nodes + index * 0.09, duration: 1.1, ease: EASE }}
    >
      <g transform={`translate(${c.node.x} ${c.node.y})`}>
        <circle
          className="net-halo"
          r={NODE_RADIUS + 16}
          fill={`url(#halo-${c.tone === "azure" ? "azure" : "teal"})`}
          style={{ animationDelay: `${index * 0.8}s` }}
        />
        <circle className="net-hover-ring" r={NODE_RADIUS + 9} fill="none" stroke={color} strokeWidth="1" />
        <circle r={NODE_RADIUS} fill="#0B2340" fillOpacity="0.92" />
        <circle className="net-ring" r={NODE_RADIUS} fill="none" stroke={color} strokeOpacity="0.7" strokeWidth="1.25" />
        <circle r={NODE_RADIUS - 8} fill="none" stroke={color} strokeOpacity="0.22" strokeWidth="1" />
        <circle r="3.5" fill={color} />
        <text
          className="net-label"
          x={labelX}
          y={labelY}
          textAnchor={c.align}
          fill="#F3F7FC"
          fontSize={labelSize}
          fontFamily="var(--font-mono)"
          letterSpacing="0.04em"
        >
          {c.label}
        </text>
      </g>
    </motion.g>
  );
}

export function CloudNetwork({ className }: { className?: string }) {
  const layoutName = useLayout();
  const layout = LAYOUTS[layoutName];
  const connections = useMemo(() => buildConnections(layout), [layout]);
  const still = useReducedMotion() ?? false;

  const fade = (delay: number, duration = 1.2) =>
    still
      ? { initial: false as const }
      : { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { delay, duration, ease: EASE } };

  return (
    <svg
      className={className}
      viewBox={layout.viewBox}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-labelledby="network-title"
    >
      <title id="network-title">
        The OwnCloud network: a cloud at the centre, connected to six capabilities.
      </title>

      <defs>
        {connections.map((c) => (
          <PathGradient key={c.id} c={c} />
        ))}

        <linearGradient id="cloud-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="0.55" stopColor="#E3EEFF" />
          <stop offset="1" stopColor="#A7C7FF" />
        </linearGradient>
        <radialGradient id="cloud-sheen" cx="0.38" cy="0.18" r="0.6">
          <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.9" />
          <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="cloud-edge" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.9" />
          <stop offset="1" stopColor="#528BFF" stopOpacity="0.4" />
        </linearGradient>
        <radialGradient id="ambient" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor={TEAL} stopOpacity="0.16" />
          <stop offset="0.45" stopColor={AZURE} stopOpacity="0.07" />
          <stop offset="1" stopColor={AZURE} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="halo-teal">
          <stop offset="0.5" stopColor={TEAL} stopOpacity="0.16" />
          <stop offset="1" stopColor={TEAL} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="halo-azure">
          <stop offset="0.5" stopColor={AZURE} stopOpacity="0.16" />
          <stop offset="1" stopColor={AZURE} stopOpacity="0" />
        </radialGradient>
        <filter id="blur-soft" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
        <filter id="blur-wide" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="26" />
        </filter>
      </defs>

      {/* Ambient light behind the cloud */}
      <motion.ellipse
        cx={CLOUD_CENTER.x}
        cy={CLOUD_CENTER.y}
        rx="420"
        ry="300"
        fill="url(#ambient)"
        {...fade(T.cloud, 2)}
      />

      {/* Light diffusion around the connections */}
      {layout.glow && (
        <motion.g filter="url(#blur-soft)" {...fade(T.glow, 1.6)}>
          {connections.map((c) => (
            <path
              key={c.id}
              d={c.d}
              fill="none"
              stroke={`url(#grad-${c.id})`}
              strokeWidth={layout.stroke * 4}
              strokeLinecap="round"
              opacity="0.45"
            />
          ))}
        </motion.g>
      )}

      {/* Branch stubs */}
      <motion.g {...fade(T.nodes + 0.3, 1.2)}>
        {connections.map(
          (c) =>
            c.stub && (
              <g key={c.id} stroke={endColor(c.tone)} fill={endColor(c.tone)}>
                <path d={c.stub.d} strokeOpacity="0.28" strokeWidth={layout.stroke * 0.8} />
                <circle cx={c.stub.dot.x} cy={c.stub.dot.y} r={layout.stroke * 1.8} fillOpacity="0.55" stroke="none" />
              </g>
            ),
        )}
      </motion.g>

      {/* Connection paths, revealed from each endpoint towards the cloud */}
      {connections.map((c, i) => (
        <motion.path
          key={`${layoutName}-${c.id}`}
          d={c.d}
          fill="none"
          stroke={`url(#grad-${c.id})`}
          strokeWidth={layout.stroke}
          strokeLinecap="round"
          initial={still ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ delay: T.paths + i * 0.12, duration: 1.8, ease: EASE }}
        />
      ))}

      {/* Live pulses travelling outward from the cloud */}
      {!still &&
        connections.map((c, i) => (
          <path
            key={`pulse-${c.id}`}
            className="net-pulse"
            d={c.d}
            pathLength={1}
            fill="none"
            stroke={`url(#grad-${c.id})`}
            strokeWidth={layout.stroke * 1.6}
            strokeLinecap="round"
            style={{ animationDelay: `${T.pulses + i * 1.3}s` }}
          />
        ))}

      {/* Glow developing around the cloud */}
      <motion.path
        d={CLOUD_PATH}
        fill={TEAL}
        filter="url(#blur-wide)"
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 0.32 }}
        transition={{ delay: T.glow, duration: 2, ease: EASE }}
      />

      {/* The cloud — drawn last so it always masks the paths */}
      <motion.g
        initial={still ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: T.cloud, duration: 1.4, ease: EASE }}
      >
        <ellipse cx="600" cy="404" rx="130" ry="12" fill={AZURE} opacity="0.28" filter="url(#blur-soft)" />
        <path d={CLOUD_PATH} fill="url(#cloud-fill)" />
        <path d={CLOUD_PATH} fill="url(#cloud-sheen)" />
        <path d={CLOUD_PATH} fill="none" stroke="url(#cloud-edge)" strokeWidth="1" opacity="0.6" />
      </motion.g>

      {connections.map((c, i) => (
        <Node key={c.id} c={c} index={i} labelSize={layout.labelSize} still={still} />
      ))}
    </svg>
  );
}
