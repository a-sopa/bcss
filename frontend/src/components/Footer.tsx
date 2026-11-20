import { Brand, Container } from "./ui";

const LINKS = [
  { href: "#product", label: "Product" },
  { href: "#infrastructure", label: "Infrastructure" },
  { href: "#docs", label: "Documentation" },
  { href: "#about", label: "About" },
];

export function Footer() {
  return (
    <footer className="border-t border-line">
      <Container className="flex flex-col gap-8 py-12 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-col gap-3">
          <Brand />
          <p className="text-[13px] text-muted">
            Designed and developed in Europe · © {new Date().getFullYear()} OwnCloud
          </p>
        </div>
        <ul className="flex flex-wrap gap-x-8 gap-y-3">
          {LINKS.map((link) => (
            <li key={link.href}>
              <a href={link.href} className="text-[13px] text-muted transition-colors duration-300 hover:text-ink">
                {link.label}
              </a>
            </li>
          ))}
        </ul>
      </Container>
    </footer>
  );
}
