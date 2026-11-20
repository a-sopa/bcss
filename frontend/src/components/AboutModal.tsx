import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "motion/react";
import { TEAM, photoOf, type Member } from "../lib/team";

const COLS = 10;
const ROWS = 32; // more than any card is tall; the overflow fades out at the bottom
const FLIP_MS = 120;

const randomColumn = () => Array.from({ length: ROWS }, () => (Math.random() < 0.5 ? "0" : "1")).join("\n");

/**
 * Columns of flickering binary covering a card. On hover or focus each column drops
 * out of the card, one after another, like a curtain falling.
 */
function BinaryCurtain() {
  const cols = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    const flip = window.setInterval(() => {
      for (const col of cols.current) {
        if (!col || Math.random() > 0.4) continue;
        const bits = col.textContent!.split("\n");
        const i = (Math.random() * bits.length) | 0;
        bits[i] = bits[i] === "0" ? "1" : "0";
        col.textContent = bits.join("\n");
      }
    }, FLIP_MS);
    return () => clearInterval(flip);
  }, []);

  return (
    <div className="curtain absolute inset-0 flex justify-between overflow-hidden px-4 pt-3" aria-hidden="true">
      {Array.from({ length: COLS }, (_, i) => (
        <span
          key={i}
          ref={(el) => void (cols.current[i] = el)}
          className="curtain-col"
          style={{ transitionDelay: `${(i % 2 ? COLS - i : i) * 35}ms` }}
        >
          {randomColumn()}
        </span>
      ))}
    </div>
  );
}

function MemberCard({ member, index }: { member: Member; index: number }) {
  return (
    <motion.li
      className="team-card group relative aspect-[3/4] overflow-hidden rounded-2xl border border-line bg-[#000614]/70 outline-none"
      tabIndex={0}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 + index * 0.06, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
    >
      <BinaryCurtain />
      <img
        src={photoOf(member)}
        alt=""
        loading="lazy"
        className="team-card-photo pointer-events-none absolute inset-x-0 bottom-0 mx-auto h-[88%] w-full object-contain object-bottom"
      />
      <div className="team-card-body absolute inset-0 flex flex-col justify-end bg-gradient-to-t from-[#000614] via-[#000614]/70 via-30% to-transparent to-55% p-5">
        <span className="font-code text-[11px] tracking-[0.25em] text-teal/70">0{index + 1}</span>
        <h3 className="mt-2 font-code text-xl leading-tight text-ink">{member.name}</h3>
        <a
          href={`https://github.com/${member.github}`}
          target="_blank"
          rel="noreferrer"
          className="mt-1 font-code text-sm text-teal hover:underline"
        >
          @{member.github}
        </a>
        {member.funFact && <p className="mt-3 text-sm leading-relaxed text-muted">{member.funFact}</p>}
      </div>
    </motion.li>
  );
}

export function AboutModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto bg-[#000614]/75 p-4 backdrop-blur-md sm:p-8"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          onClick={onClose}
        >
          <motion.div
            ref={dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="about-title"
            tabIndex={-1}
            className="about-panel relative my-auto w-full max-w-6xl rounded-3xl border border-teal/15 p-6 outline-none sm:p-10"
            initial={{ y: 24, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: 24, scale: 0.98 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-6">
              <div>
                <p className="font-code text-xs tracking-[0.3em] text-teal uppercase">About us</p>
                <h2 id="about-title" className="mt-3 font-code text-3xl text-ink sm:text-4xl">
                  Our team
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="grid size-10 place-items-center rounded-full border border-line text-muted transition-colors hover:border-teal/50 hover:text-ink"
              >
                <span className="sr-only">Close</span>
                <svg viewBox="0 0 16 16" className="size-4" aria-hidden="true">
                  <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            <ul className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-5">
              {TEAM.map((member, i) => (
                <MemberCard key={member.github} member={member} index={i} />
              ))}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
