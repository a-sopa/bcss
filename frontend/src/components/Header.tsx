import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { AboutModal } from "./AboutModal";
import { Brand, Container } from "./ui";

/** Hidden over the landing animation; slides down once the page starts scrolling. */
export function Header() {
  const [shown, setShown] = useState(false);
  const [about, setAbout] = useState(false);
  const closeAbout = useCallback(() => setAbout(false), []);

  useEffect(() => {
    const onScroll = () => setShown(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      <motion.header
        className="fixed inset-x-0 top-0 z-50 border-b border-line bg-navy-950/70 backdrop-blur-xl"
        initial={false}
        animate={shown ? { y: 0, opacity: 1 } : { y: "-100%", opacity: 0 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        inert={!shown}
      >
        <Container className="flex h-20 max-w-7xl items-center justify-between">
          <Brand />
          <nav aria-label="Primary" className="flex items-center gap-2 font-code text-[15px] sm:gap-4">
            <button
              type="button"
              onClick={() => setAbout(true)}
              className="rounded-full px-4 py-2 tracking-[0.04em] text-muted transition-colors hover:text-ink"
            >
              About us
            </button>
            <a
              href="#/console"
              className="rounded-full border border-teal/40 px-5 py-2 tracking-[0.04em] text-teal transition-[background-color,border-color] hover:border-teal hover:bg-teal/10"
            >
              Sign in
            </a>
          </nav>
        </Container>
      </motion.header>
      <AboutModal open={about} onClose={closeAbout} />
    </>
  );
}
