import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Brand, Button, Container, cx } from "./ui";

const LINKS = [
  { href: "#product", label: "Product" },
  { href: "#infrastructure", label: "Infrastructure" },
  { href: "#docs", label: "Documentation" },
  { href: "#about", label: "About" },
];

export function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const solid = scrolled || open;

  return (
    <header
      className={cx(
        "fixed inset-x-0 top-0 z-50 border-b transition-[background-color,border-color,backdrop-filter] duration-500",
        solid ? "border-line bg-navy-950/75 backdrop-blur-xl" : "border-transparent",
      )}
    >
      <Container className="flex h-16 items-center justify-between">
        <Brand />

        <nav aria-label="Primary" className="hidden items-center gap-10 md:flex">
          <ul className="flex items-center gap-9">
            {LINKS.map((link) => (
              <li key={link.href}>
                <a href={link.href} className="text-[13px] text-muted transition-colors duration-300 hover:text-ink">
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
          <Button href="#/console" size="sm">
            Get Started
          </Button>
        </nav>

        <button
          type="button"
          className="relative -mr-2 grid size-10 place-items-center rounded-full md:hidden"
          aria-expanded={open}
          aria-controls="mobile-nav"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
          <span
            className={cx(
              "absolute h-px w-5 bg-ink transition-transform duration-300",
              open ? "rotate-45" : "-translate-y-[4px]",
            )}
          />
          <span
            className={cx(
              "absolute h-px w-5 bg-ink transition-transform duration-300",
              open ? "-rotate-45" : "translate-y-[4px]",
            )}
          />
        </button>
      </Container>

      <AnimatePresence>
        {open && (
          <motion.nav
            id="mobile-nav"
            aria-label="Primary"
            className="border-t border-line md:hidden"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <Container className="flex flex-col gap-1 py-5">
              {LINKS.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className="py-3 font-display text-lg text-ink/90"
                >
                  {link.label}
                </a>
              ))}
              <Button href="#/console" className="mt-4" onClick={() => setOpen(false)}>
                Get Started
              </Button>
            </Container>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
