import { Container, Reveal, Section, SectionHeading } from "../components/ui";

const FEATURES = [
  {
    title: "Post-quantum readiness",
    text: "Classical algorithms such as RSA and ECDSA are identified with evidence and exported as a CycloneDX cryptography bill of materials.",
  },
  {
    title: "Explanations, not black boxes",
    text: "Every alert carries the evidence behind it, together with a readable account of what happened.",
  },
  {
    title: "Human in the loop",
    text: "Automated remediations are proposed first and applied once approved.",
  },
];

export function Security() {
  return (
    <Section aria-labelledby="security-title" className="bg-navy-900/40">
      <Container className="grid gap-14 lg:grid-cols-[1fr_1.15fr] lg:gap-20">
        <SectionHeading
          id="security-title"
          eyebrow="Security & reliability"
          title="Decisions you can trace."
          lede="Deterministic engines decide. Language models explain. People stay in control."
        />

        <ul className="divide-y divide-line border-y border-line">
          {FEATURES.map((f, i) => (
            <Reveal as="li" key={f.title} delay={i * 0.08} className="grid gap-2 py-7 sm:grid-cols-[3rem_1fr]">
              <span className="font-mono text-xs text-teal sm:pt-1">{String(i + 1).padStart(2, "0")}</span>
              <div>
                <h3 className="font-display text-lg font-semibold tracking-[-0.01em]">{f.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">{f.text}</p>
              </div>
            </Reveal>
          ))}
        </ul>
      </Container>
    </Section>
  );
}
