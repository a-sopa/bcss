import { Container, Eyebrow, Reveal, Section, cx } from "../components/ui";

const PRINCIPLES = [
  {
    title: "European by origin",
    text: "Conceived, designed and engineered in Europe, by a European team.",
  },
  {
    title: "Your intelligence, on your infrastructure",
    text: "The AI runs on open models inside your own environment — no third-party AI service in the loop.",
  },
  {
    title: "Open-source foundations",
    text: "Every layer is built on open-source software you can inspect.",
  },
];

const TIMELINE = [
  { time: "T − 3 h", text: <>Event detected in the news: <strong className="font-medium text-ink">Sporting × Benfica</strong>, Lisbon.</> },
  { time: "T − 45 min", text: "Forecast: a sharp rise in streaming demand at kick-off." },
  { time: "T − 20 min", text: "Additional capacity started ahead of the spike." },
  { time: "Kick-off", text: "Demand arrives. The network is already ready.", now: true },
];

export function Europe() {
  return (
    <Section id="about" aria-labelledby="europe-title" className="overflow-hidden">
      <div className="europe-atmosphere absolute inset-0 -z-10" aria-hidden="true" />

      {/* Oversized watermark word */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute top-6 left-1/2 -translate-x-1/2 font-display text-[22vw] leading-none font-bold tracking-[-0.06em] text-ink/[0.025] select-none lg:text-[15rem]"
      >
        EUROPE
      </span>

      <Container className="relative grid items-start gap-16 lg:grid-cols-[1.05fr_1fr] lg:gap-20">
        <Reveal>
          <Eyebrow>About</Eyebrow>
          <h2
            id="europe-title"
            className="mt-5 font-display text-[2.4rem] leading-[1.05] font-semibold tracking-[-0.035em] sm:text-[3.4rem]"
          >
            Made in <span className="text-gradient">Europe</span>.
            <br />
            Built for Europe.
          </h2>
          <p className="mt-6 max-w-lg text-[15px] leading-relaxed text-muted sm:text-base">
            OwnCloud is designed and developed in Europe — with the people, the events and the rhythm of the
            continent at the centre of how it works.
          </p>

          <ul className="mt-12 divide-y divide-line border-y border-line">
            {PRINCIPLES.map((p) => (
              <li key={p.title} className="py-5">
                <h3 className="font-display text-[15px] font-semibold">{p.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{p.text}</p>
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal delay={0.15}>
          <figure className="rounded-3xl border border-line bg-navy-900/50 p-7 backdrop-blur-sm sm:p-9">
            <figcaption>
              <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted">Illustrative scenario</span>
              <span className="mt-3 block font-display text-xl font-semibold tracking-[-0.015em]">
                Attuned to Europe's calendar
              </span>
            </figcaption>

            <ol className="relative mt-8">
              <span
                aria-hidden="true"
                className="absolute top-2 bottom-2 left-[5px] w-px bg-gradient-to-b from-line via-teal/30 to-teal/70"
              />
              {TIMELINE.map((item) => (
                <li key={item.time} className="relative pb-7 pl-8 last:pb-0">
                  <span
                    aria-hidden="true"
                    className={cx(
                      "absolute top-[7px] left-0 size-[11px] rounded-full border",
                      item.now
                        ? "border-teal bg-teal shadow-[0_0_18px_rgb(66_214_197/0.6)]"
                        : "border-teal/50 bg-navy-900",
                    )}
                  />
                  <span className={cx("font-mono text-xs", item.now ? "text-teal" : "text-muted")}>{item.time}</span>
                  <p className="mt-1 text-[15px] leading-relaxed text-ink/80">{item.text}</p>
                </li>
              ))}
            </ol>
          </figure>
        </Reveal>
      </Container>
    </Section>
  );
}
