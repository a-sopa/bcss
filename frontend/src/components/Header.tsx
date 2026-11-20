import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { Brand, Button, Container } from "./ui";

/** Hidden over the landing animation; slides down once the page starts scrolling. */
export function Header() {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const onScroll = () => setShown(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <motion.header
      className="fixed inset-x-0 top-0 z-50 border-b border-line bg-navy-950/70 backdrop-blur-xl"
      initial={false}
      animate={shown ? { y: 0, opacity: 1 } : { y: "-100%", opacity: 0 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      inert={!shown}
    >
      <Container className="flex h-16 items-center justify-between">
        <Brand />
        <Button href="#/console" size="sm">
          Get Started
        </Button>
      </Container>
    </motion.header>
  );
}
