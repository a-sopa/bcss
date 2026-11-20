import { Container, Reveal, Section, SectionHeading } from "../components/ui";

const PILLARS = [
  {
    title: "Observe",
    text: "Metrics, logs and network activity from every container are collected in one place.",
  },
  {
    title: "Understand",
    text: "Models learn what normal looks like and explain what changed, in plain language.",
  },
  {
    title: "Act",
    text: "Capacity, alerts and remediations follow — proposed by AI, approved by you.",
  },
];

export function Overview() {
  return (
    <Section id="infrastructure" aria-labelledby="overview-title">
      <Container>
        <SectionHeading
          id="overview-title"
          eyebrow="Infrastructure"
          title={
            <>
              One cloud at the centre.
              <br />
              <span className="text-muted">Intelligence at every edge.</span>
            </>
          }
          lede="OwnCloud runs your workloads in containers and watches over them continuously. Every signal flows back to the centre, where AI turns it into understanding and action."
        />

        <ol className="mt-16 grid gap-10 sm:mt-20 md:grid-cols-3 md:gap-12">
          {PILLARS.map((pillar, i) => (
            <Reveal as="li" key={pillar.title} delay={i * 0.08} className="border-t border-line pt-6">
              <span className="font-mono text-xs text-teal">{String(i + 1).padStart(2, "0")}</span>
              <h3 className="mt-4 font-display text-lg font-semibold tracking-[-0.01em]">{pillar.title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{pillar.text}</p>
            </Reveal>
          ))}
        </ol>
      </Container>
    </Section>
  );
}
