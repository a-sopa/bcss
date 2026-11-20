import type { ComponentProps, ReactNode } from "react";
import { motion } from "motion/react";
import { LOGO_PATHS, LOGO_VIEWBOX } from "../lib/logo";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Container({ className, ...props }: ComponentProps<"div">) {
  return <div className={cx("mx-auto w-full max-w-6xl px-5 sm:px-8", className)} {...props} />;
}

type ButtonProps = ComponentProps<"a"> & {
  variant?: "primary" | "ghost";
  size?: "sm" | "md";
};

export function Button({ variant = "primary", size = "md", className, ...props }: ButtonProps) {
  return (
    <a
      className={cx(
        "group inline-flex items-center justify-center gap-2 rounded-full font-code tracking-[0.04em] whitespace-nowrap",
        "transition-[background-color,border-color,color,box-shadow,transform] duration-300 ease-(--ease-soft)",
        size === "sm" ? "h-9 px-4 text-[13px]" : "h-12 px-6 text-sm",
        variant === "primary"
          ? "bg-teal text-navy-950 shadow-[0_10px_30px_-14px_rgb(66_214_197/0.7)] hover:bg-teal-soft hover:shadow-[0_14px_36px_-14px_rgb(66_214_197/0.9)]"
          : "border border-line text-ink hover:border-teal/35 hover:bg-white/[0.03]",
        className,
      )}
      {...props}
    />
  );
}

export function ArrowIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={cx("size-4", className)}>
      <path
        d="M3 8h10M9 4l4 4-4 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox={LOGO_VIEWBOX} aria-hidden="true" className={className} fill="currentColor">
      {LOGO_PATHS.map((d) => (
        <path key={d.slice(0, 24)} d={d} />
      ))}
    </svg>
  );
}

export function Brand() {
  return (
    <a href="#top" className="inline-flex items-center gap-3" aria-label="BCSS home">
      <BrandMark className="h-[22px] w-[39px] text-teal" />
      <span className="font-code text-[19px] tracking-[0.12em] text-ink">BCSS</span>
    </a>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cx("font-mono text-[11px] font-medium uppercase tracking-[0.2em] text-teal", className)}>
      {children}
    </p>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  lede,
  id,
  className,
}: {
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  id: string;
  className?: string;
}) {
  return (
    <Reveal className={cx("max-w-2xl", className)}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2
        id={id}
        className="mt-5 font-display text-[2rem] leading-[1.12] font-semibold tracking-[-0.025em] text-balance sm:text-[2.6rem]"
      >
        {title}
      </h2>
      {lede && <p className="mt-5 text-[15px] leading-relaxed text-muted sm:text-base">{lede}</p>}
    </Reveal>
  );
}

export function Section({ className, ...props }: ComponentProps<"section">) {
  return <section className={cx("relative py-24 sm:py-32", className)} {...props} />;
}

/** Gentle fade-and-rise when an element first scrolls into view. */
export function Reveal({
  children,
  className,
  delay = 0,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  as?: "div" | "li";
}) {
  const Tag = as === "li" ? motion.li : motion.div;
  return (
    <Tag
      className={className}
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -80px 0px" }}
      transition={{ duration: 0.9, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </Tag>
  );
}
