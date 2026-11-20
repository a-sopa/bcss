import { Container, Reveal, Section, SectionHeading, cx } from "../components/ui";

const CAPABILITIES = [
  {
    title: "Anomaly detection",
    text: "Learns each container's normal behaviour and flags what deviates — without fixed thresholds.",
  },
  {
    title: "Incident analysis",
    text: "Correlates metrics and logs and writes a clear explanation of the probable cause.",
  },
  {
    title: "Event-aware scaling",
    text: "Reads European news and event calendars to anticipate demand and add capacity before it arrives.",
  },
  {
    title: "Quantum readiness",
    text: "Finds quantum-vulnerable cryptography in code and traffic, with evidence and a migration path.",
  },
  {
    title: "Code safety gate",
    text: "Analyses code before it is deployed, so risky changes are caught before they run.",
  },
  {
    title: "Runtime security",
    text: "Watches for suspicious activity such as brute-force attempts and unexpected behaviour changes.",
  },
];

function NodeGlyph({ azure }: { azure: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "relative grid size-9 place-items-center rounded-full border bg-navy-950/60",
        azure ? "border-azure/50" : "border-teal/50",
      )}
    >
      <span className={cx("absolute inset-[7px] rounded-full border", azure ? "border-azure/20" : "border-teal/20")} />
      <span className={cx("size-[5px] rounded-full", azure ? "bg-azure" : "bg-teal")} />
    </span>
  );
}

export function Capabilities() {
  return (
    <Section id="product" aria-labelledby="capabilities-title" className="bg-navy-900/40">
      <Container>
        <SectionHeading
          id="capabilities-title"
          eyebrow="Product"
          title={
            <>
              Six capabilities.
              <br />
              <span className="text-muted">One connected network.</span>
            </>
          }
          lede="Each node in the network is an AI capability working on the same live picture of your infrastructure."
        />

        <ul className="mt-16 grid gap-x-12 gap-y-12 sm:mt-20 sm:grid-cols-2 lg:grid-cols-3 lg:gap-y-16">
          {CAPABILITIES.map((item, i) => (
            <Reveal as="li" key={item.title} delay={(i % 3) * 0.08} className="flex flex-col">
              <NodeGlyph azure={i % 2 === 1} />
              <h3 className="mt-6 font-display text-lg font-semibold tracking-[-0.01em]">{item.title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{item.text}</p>
            </Reveal>
          ))}
        </ul>
      </Container>
    </Section>
  );
}
