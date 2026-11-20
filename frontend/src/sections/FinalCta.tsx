import { BrandMark, Button, Container, Reveal, Section } from "../components/ui";

export function FinalCta() {
  return (
    <Section id="start" aria-labelledby="final-title" className="overflow-hidden border-t border-line">
      <div className="final-atmosphere absolute inset-0 -z-10" aria-hidden="true" />
      <Container>
        <Reveal className="flex flex-col items-center text-center">
          <BrandMark className="h-11 w-16 drop-shadow-[0_0_30px_rgb(66_214_197/0.35)]" />
          <h2
            id="final-title"
            className="mt-10 font-display text-[2.2rem] leading-[1.08] font-semibold tracking-[-0.03em] text-balance sm:text-[3rem]"
          >
            A cloud at the centre of it all.
          </h2>
          <p className="mt-5 text-[15px] text-muted sm:text-base">
            European technology. Connected infrastructure.
          </p>
          <div className="mt-10 flex w-full flex-col justify-center gap-3 sm:w-auto sm:flex-row">
            <Button href="#/console">Get Started</Button>
            <Button href="#docs" variant="ghost">
              Read the documentation
            </Button>
          </div>
        </Reveal>
      </Container>
    </Section>
  );
}
