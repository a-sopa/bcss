import { useEffect, useState, type CSSProperties } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CloudNetwork, T } from "./CloudNetwork";
import { TITLE_Y } from "../lib/traces";

const TITLE = "BCSS";
const TYPE_START = 1.35; // right after the logo has faded in
const TYPE_STEP = 0.16;

/** Types `text` one character at a time after `delay` seconds. */
function useTyped(text: string, delay: number, step: number, still: boolean) {
  const [count, setCount] = useState(still ? text.length : 0);
  useEffect(() => {
    if (still) return setCount(text.length);
    const timers = Array.from({ length: text.length }, (_, i) =>
      window.setTimeout(() => setCount(i + 1), (delay + i * step) * 1000),
    );
    return () => timers.forEach(clearTimeout);
  }, [text, delay, step, still]);
  return text.slice(0, count);
}

export function Hero() {
  const still = useReducedMotion() ?? false;
  const typed = useTyped(TITLE, TYPE_START, TYPE_STEP, still);

  return (
    <section
      id="top"
      aria-labelledby="hero-title"
      className="relative isolate h-[100svh] min-h-[560px] overflow-hidden"
      // One SVG unit in CSS pixels: the network uses a 1600×900 viewBox with `slice`.
      style={{ "--u": "max(100vw / 1600, max(100svh, 560px) / 900)" } as CSSProperties}
    >
      <div className="hero-atmosphere absolute inset-0 -z-10" aria-hidden="true" />
      <CloudNetwork className="absolute inset-0 h-full w-full" />

      <div
        className="absolute inset-x-0 flex flex-col items-center px-4 text-center"
        style={{ top: `calc(50% + ${TITLE_Y} * var(--u))` }}
      >
        <h1
          id="hero-title"
          aria-label={TITLE}
          className="font-code tracking-[0.14em] whitespace-nowrap"
          style={{ fontSize: "clamp(2.4rem, min(92 * var(--u), 12vw), 7.5rem)", lineHeight: 1.1 }}
        >
          <span aria-hidden="true" className="mr-[0.35em] text-teal/70">
            &gt;
          </span>
          <span aria-hidden="true" className="text-ink">
            {typed}
          </span>
          <span aria-hidden="true" className="type-caret" />
        </h1>

      </div>

      <motion.a
        href="#made-in-europe"
        aria-label="Scroll down"
        className="absolute bottom-8 left-1/2 -translate-x-1/2"
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: T.pulses, duration: 1.2 }}
      >
        <span className="scroll-cue-line block h-12 w-px" aria-hidden="true" />
      </motion.a>
    </section>
  );
}
