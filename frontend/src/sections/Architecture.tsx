import { BrandMark, Container, Reveal, Section, SectionHeading, cx } from "../components/ui";

const STEPS = [
  { title: "Workloads", text: "Containerised services" },
  { title: "Telemetry", text: "Metrics, logs and traffic" },
  { title: "AI engine", text: "Detect, forecast, explain", core: true },
  { title: "Action", text: "Scale, alert, remediate" },
];

const STACK = ["Docker", "Prometheus", "Loki", "Grafana", "Ollama"];

export function Architecture() {
  return (
    <Section aria-labelledby="architecture-title">
      <Container>
        <SectionHeading
          id="architecture-title"
          eyebrow="Architecture"
          title="From signal to decision."
          lede="A single path connects every workload to the intelligence at the centre — and back again."
        />

        <Reveal className="relative mt-16 sm:mt-20">
          {/* Connecting line: vertical on mobile, horizontal from md up */}
          <span
            aria-hidden="true"
            className="absolute top-4 bottom-4 left-[17px] w-px bg-gradient-to-b from-teal/0 via-teal/40 to-azure/0 md:hidden"
          />
          <span
            aria-hidden="true"
            className="absolute top-[18px] right-[12.5%] left-[12.5%] hidden h-px bg-gradient-to-r from-teal/10 via-teal/45 to-azure/10 md:block"
          />

          <ol className="relative grid gap-10 md:grid-cols-4 md:gap-6">
            {STEPS.map((step) => (
              <li key={step.title} className="flex items-start gap-5 md:flex-col md:items-center md:text-center">
                <span
                  aria-hidden="true"
                  className={cx(
                    "relative grid size-9 shrink-0 place-items-center rounded-full border bg-navy-950",
                    step.core
                      ? "border-teal/60 shadow-[0_0_40px_-6px_rgb(66_214_197/0.55)]"
                      : "border-line",
                  )}
                >
                  {step.core ? (
                    <BrandMark className="h-[11px] w-4" />
                  ) : (
                    <span className="size-[5px] rounded-full bg-muted/70" />
                  )}
                </span>
                <div className="md:mt-5">
                  <h3 className={cx("font-display text-base font-semibold", step.core && "text-teal")}>
                    {step.title}
                  </h3>
                  <p className="mt-1 text-sm text-muted">{step.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </Reveal>

        <Reveal className="mt-20 flex flex-col gap-4 border-t border-line pt-8 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted">Built on open source</span>
          <ul className="flex flex-wrap gap-x-7 gap-y-2">
            {STACK.map((name) => (
              <li key={name} className="font-display text-[15px] font-medium text-ink/75">
                {name}
              </li>
            ))}
          </ul>
        </Reveal>
      </Container>
    </Section>
  );
}
