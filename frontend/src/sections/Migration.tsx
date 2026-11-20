import { ArrowIcon, Button, Container, Reveal, Section, SectionHeading } from "../components/ui";

const SOURCES = [
  {
    title: "Lambda functions",
    text: "SAM templates, Serverless Framework projects or a plain handler. Your function runs unchanged behind an emulated API Gateway.",
  },
  {
    title: "Elastic Beanstalk apps",
    text: "Procfile, application.py and .ebextensions are understood. Environment variables come with the app.",
  },
  {
    title: "Containers",
    text: "Anything with a Dockerfile — from ECS, App Runner or elsewhere — deploys as it is.",
  },
];

const MAPPINGS = [
  ["Amazon S3", "MinIO"],
  ["DynamoDB", "ScyllaDB Alternator"],
  ["Amazon SQS", "ElasticMQ"],
  ["Secrets Manager", "Environment variables"],
  ["CloudWatch", "Built-in logs & metrics"],
];

export function Migration() {
  return (
    <Section id="migrate" aria-labelledby="migrate-title">
      <Container className="grid gap-14 lg:grid-cols-[1.1fr_1fr] lg:gap-20">
        <div>
          <SectionHeading
            id="migrate-title"
            eyebrow="Migration"
            title={
              <>
                Leaving AWS?
                <br />
                <span className="text-muted">Bring your apps as they are.</span>
              </>
            }
            lede="Upload an exported project. OwnCloud recognises where it came from, imports its configuration, maps every AWS dependency to an open-source equivalent and flags hard-coded keys — before anything runs."
          />

          <ul className="mt-12 divide-y divide-line border-y border-line">
            {SOURCES.map((s, i) => (
              <Reveal as="li" key={s.title} delay={i * 0.08} className="py-5">
                <h3 className="font-display text-[15px] font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{s.text}</p>
              </Reveal>
            ))}
          </ul>

          <Reveal className="mt-10">
            <Button href="#/console/migrate">
              Start a migration
              <ArrowIcon className="transition-transform duration-300 group-hover:translate-x-0.5" />
            </Button>
          </Reveal>
        </div>

        <Reveal delay={0.15} className="self-center">
          <figure className="rounded-3xl border border-line bg-navy-900/50 p-7 sm:p-9">
            <figcaption className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted">
              Your AWS dependencies, mapped
            </figcaption>
            <ul className="mt-6 space-y-4">
              {MAPPINGS.map(([from, to]) => (
                <li key={from} className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-sm">
                  <span className="text-muted">{from}</span>
                  <span
                    aria-hidden="true"
                    className="h-px w-10 bg-gradient-to-r from-azure/20 to-teal/80 sm:w-16"
                  />
                  <span className="font-medium">{to}</span>
                </li>
              ))}
            </ul>
            <p className="mt-7 border-t border-line pt-5 text-xs leading-relaxed text-muted">
              S3, DynamoDB and SQS replacements speak the same API: your SDK code stays the same, only the endpoint changes.
            </p>
          </figure>
        </Reveal>
      </Container>
    </Section>
  );
}
