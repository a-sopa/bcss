import { useRef } from "react";
import { motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "motion/react";
import { ArrowIcon } from "../components/ui";

const STARS = 12;
const STAR_PATH = "M0 -10L2.35 -3.24L9.51 -3.09L3.8 1.24L5.88 8.09L0 4L-5.88 8.09L-3.8 1.24L-9.51 -3.09L-2.35 -3.24Z";

/** Where each star starts, scattered around the screen (in % of the ring box). */
const SCATTER = Array.from({ length: STARS }, (_, i) => {
  const a = (i / STARS) * Math.PI * 2 + 0.9;
  const r = 85 + ((i * 37) % 5) * 14;
  return { x: 50 + Math.cos(a) * r, y: 50 + Math.sin(a * 1.3) * r * 0.8, spin: (i % 2 ? 1 : -1) * (200 + i * 25) };
});

function Star({ i, progress }: { i: number; progress: MotionValue<number> }) {
  const a = (i / STARS) * Math.PI * 2 - Math.PI / 2;
  const ring = { x: 50 + Math.cos(a) * 44, y: 50 + Math.sin(a) * 44 };
  const from = SCATTER[i];
  // Each star lands a touch after the previous one.
  const start = 0.02 + i * 0.022;
  const end = start + 0.3;

  const left = useTransform(progress, [start, end], [`${from.x}%`, `${ring.x}%`]);
  const top = useTransform(progress, [start, end], [`${from.y}%`, `${ring.y}%`]);
  const rotate = useTransform(progress, [start, end], [from.spin, 0]);
  const scale = useTransform(progress, [start, end, end + 0.05, end + 0.12], [0.2, 1.25, 1.5, 1]);
  const opacity = useTransform(progress, [start, start + 0.08], [0, 1]);

  return (
    <motion.svg
      viewBox="-12 -12 24 24"
      className="eu-star absolute size-[clamp(18px,3.6vmin,34px)] -translate-x-1/2 -translate-y-1/2"
      style={{ left, top, rotate, scale, opacity }}
    >
      <path d={STAR_PATH} fill="url(#gold)" />
    </motion.svg>
  );
}

/** Gold dust that drifts upward as you scroll. */
function Dust({ progress }: { progress: MotionValue<number> }) {
  const y = useTransform(progress, [0, 1], ["10%", "-25%"]);
  const opacity = useTransform(progress, [0, 0.2, 0.85, 1], [0, 1, 1, 0.4]);
  return (
    <motion.div className="pointer-events-none absolute inset-0" style={{ y, opacity }} aria-hidden="true">
      {Array.from({ length: 40 }, (_, i) => (
        <span
          key={i}
          className="gold-dust"
          style={{
            left: `${(i * 61) % 100}%`,
            top: `${(i * 37) % 100}%`,
            animationDelay: `${(i % 9) * 0.45}s`,
            scale: `${0.5 + (i % 4) * 0.35}`,
          }}
        />
      ))}
    </motion.div>
  );
}

export function MadeInEurope() {
  const ref = useRef<HTMLElement>(null);
  const still = useReducedMotion() ?? false;
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const progress = useTransform(scrollYProgress, (v) => (still ? 1 : v));

  const ringRotate = useTransform(progress, [0.4, 1], [0, 40]);
  const halo = useTransform(progress, [0.3, 0.6], [0, 1]);
  const line1 = useTransform(progress, [0.1, 0.28], [0, 1]);
  const line1y = useTransform(progress, [0.1, 0.28], [24, 0]);
  const line2 = useTransform(progress, [0.28, 0.46], [0, 1]);
  const line2y = useTransform(progress, [0.28, 0.46], [24, 0]);
  const cta = useTransform(progress, [0.58, 0.72], [0, 1]);
  const ctaScale = useTransform(progress, [0.58, 0.72], [0.85, 1]);
  const ctaEvents = useTransform(cta, (v) => (v > 0.5 ? "auto" : "none"));

  return (
    <section ref={ref} id="made-in-europe" aria-labelledby="europe-intro-title" className="relative h-[320svh]">
      <div className="sticky top-0 flex h-[100svh] items-center justify-center overflow-hidden">
        <div className="europe-intro-atmosphere absolute inset-0 -z-10" aria-hidden="true" />
        <Dust progress={progress} />

        <svg width="0" height="0" className="absolute" aria-hidden="true">
          <defs>
            <linearGradient id="gold" x1="0" y1="-1" x2="0" y2="1">
              <stop offset="0" stopColor="#FFF1A8" />
              <stop offset="0.5" stopColor="#FFCC00" />
              <stop offset="1" stopColor="#E0A100" />
            </linearGradient>
          </defs>
        </svg>

        <div className="relative aspect-square w-[min(94vw,88svh)]">
          <motion.div
            className="absolute inset-[6%] rounded-full bg-[radial-gradient(circle,rgb(255_204_0/0.12),transparent_68%)]"
            style={{ opacity: halo }}
            aria-hidden="true"
          />
          <motion.div className="absolute inset-0" style={{ rotate: ringRotate }} aria-hidden="true">
            {Array.from({ length: STARS }, (_, i) => (
              <Star key={i} i={i} progress={progress} />
            ))}
          </motion.div>

          <div className="absolute inset-0 flex flex-col items-center justify-center px-[14%] text-center">
            <h2
              id="europe-intro-title"
              className="font-tech text-[clamp(2rem,6.6vmin,4.6rem)] leading-[1.05] font-semibold tracking-[-0.01em] uppercase"
            >
              <motion.span className="block" style={{ opacity: line1, y: line1y }}>
                Made in <span className="text-gold">Europe</span>,
              </motion.span>
              <motion.span className="block" style={{ opacity: line2, y: line2y }}>
                for Europe.
              </motion.span>
            </h2>
            <motion.div className="mt-[clamp(1.5rem,5vmin,3rem)]" style={{ opacity: cta, scale: ctaScale, pointerEvents: ctaEvents }}>
              <a href="#/console" className="europe-cta">
                <span className="relative">Get Started</span>
                <ArrowIcon className="relative size-5" />
              </a>
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}
