# OwnCloud — web frontend

Landing page for OwnCloud, the European cloud infrastructure with AI monitoring.

**Stack:** Vite · React 19 · TypeScript · Tailwind CSS v4 · Motion · self-hosted fonts (Manrope, Inter, JetBrains Mono — works offline).

```bash
npm install
npm run dev        # http://localhost:5180
npm run build      # type-check + production build into dist/
```

## Structure

| Path | What it is |
| --- | --- |
| `src/lib/network.ts` | Geometry of the hero network: cloud silhouette, six nodes, rounded path routing, per-breakpoint layouts |
| `src/components/CloudNetwork.tsx` | The animated SVG hero (gradients, intro sequence, pulses, hover labels) |
| `src/components/ui.tsx` | Shared primitives: `Container`, `Button`, `SectionHeading`, `Reveal`, brand mark |
| `src/sections/*` | Page sections below the hero |
| `src/index.css` | Tailwind theme tokens (palette, fonts) and SVG animation keyframes |

To change what a node represents, edit `NODES` in `src/lib/network.ts` (labels) and `CAPABILITIES` in
`src/sections/Capabilities.tsx` (descriptions). All animations respect `prefers-reduced-motion`.
