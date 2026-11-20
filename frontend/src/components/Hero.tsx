import { motion } from "motion/react";
import { CloudNetwork } from "./CloudNetwork";
import { ArrowIcon, Button, Container } from "./ui";

const EASE = [0.22, 1, 0.36, 1] as const;

const rise = (delay: number) => ({
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  transition: { delay, duration: 1, ease: EASE },
});

export function Hero() {
  return (
    <section
      id="top"
      aria-labelledby="hero-title"
      className="relative isolate flex min-h-[100svh] flex-col overflow-hidden pt-24 pb-10 sm:pt-28"
    >
      <div className="hero-atmosphere absolute inset-0 -z-10" aria-hidden="true" />

      <Container className="text-center">
        <motion.p
          {...rise(0.1)}
          className="inline-flex items-center gap-2.5 rounded-full border border-line bg-navy-900/40 py-1.5 pr-4 pl-3 font-mono text-[11px] font-medium uppercase tracking-[0.2em] text-ink/85 backdrop-blur-sm"
        >
          <span className="relative flex size-1.5" aria-hidden="true">
            <span className="absolute inset-0 rounded-full bg-teal" />
            <span className="absolute -inset-1 rounded-full bg-teal/25 blur-[3px]" />
          </span>
          Developed in Europe
        </motion.p>

        <motion.h1
          id="hero-title"
          {...rise(0.2)}
          className="mt-6 font-display text-[2.5rem] leading-[1.05] font-semibold tracking-[-0.035em] text-balance sm:text-[3.4rem] lg:text-[3.9rem]"
        >
          Your infrastructure. <span className="text-gradient">Connected.</span>
        </motion.h1>

        <motion.p
          {...rise(0.35)}
          className="mx-auto mt-5 max-w-xl text-[15px] leading-relaxed text-muted text-pretty sm:text-base"
        >
          A modern cloud infrastructure service, developed in Europe, designed to connect, power, and simplify
          the digital world.
        </motion.p>
      </Container>

      <div className="relative mx-auto mt-4 flex w-full max-w-[1320px] flex-1 items-center justify-center px-2 sm:px-6">
        <CloudNetwork className="h-[clamp(300px,52svh,600px)] w-full" />
      </div>

      <Container>
        <motion.div {...rise(1.6)} className="flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button href="#/console" className="w-full sm:w-auto">
            Get Started
          </Button>
          <Button href="#infrastructure" variant="ghost" className="w-full sm:w-auto">
            Explore the Infrastructure
            <ArrowIcon className="transition-transform duration-300 group-hover:translate-x-0.5" />
          </Button>
        </motion.div>
      </Container>

      <motion.a
        href="#infrastructure"
        aria-label="Scroll to the infrastructure overview"
        className="mx-auto mt-8 flex h-10 w-6 justify-center"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 2.6, duration: 1.2 }}
      >
        <span className="scroll-cue-line block h-full w-px" aria-hidden="true" />
      </motion.a>
    </section>
  );
}
