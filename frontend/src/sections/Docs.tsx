import { ArrowIcon, Container, Reveal, Section, SectionHeading } from "../components/ui";

const LINKS = [
  { title: "Documentation", text: "Concepts, setup and operation" },
  { title: "API reference", text: "Endpoints and event formats" },
  { title: "Source code", text: "The open-source repository" },
];

export function Docs() {
  return (
    <Section id="docs" aria-labelledby="docs-title">
      <Container className="grid gap-14 lg:grid-cols-2 lg:gap-20">
        <div>
          <SectionHeading
            id="docs-title"
            eyebrow="Documentation"
            title="Start in one command."
            lede="Guides and references for running, extending and integrating OwnCloud."
          />
          <Reveal delay={0.1}>
            <div className="mt-10 inline-flex items-center gap-3 rounded-xl border border-line bg-navy-900/70 px-5 py-4 font-mono text-sm">
              <span className="text-teal" aria-hidden="true">
                $
              </span>
              <code className="text-ink/90">docker compose up -d</code>
            </div>
          </Reveal>
        </div>

        <ul className="self-end border-t border-line">
          {LINKS.map((link, i) => (
            <Reveal as="li" key={link.title} delay={i * 0.08} className="border-b border-line">
              <a href="#docs" className="group flex items-center justify-between gap-6 py-6">
                <span>
                  <span className="block font-display text-lg font-semibold tracking-[-0.01em] transition-colors duration-300 group-hover:text-teal">
                    {link.title}
                  </span>
                  <span className="mt-1 block text-sm text-muted">{link.text}</span>
                </span>
                <ArrowIcon className="text-muted transition-[transform,color] duration-300 group-hover:translate-x-1 group-hover:text-teal" />
              </a>
            </Reveal>
          ))}
        </ul>
      </Container>
    </Section>
  );
}
