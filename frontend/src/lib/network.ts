/**
 * Geometry for the hero cloud network.
 *
 * Everything lives in one coordinate space (the cloud is centred on x = 600).
 * Each breakpoint only changes the viewBox and where the six nodes sit, so the
 * composition is re-laid out for narrow screens instead of simply shrunk.
 */

export type Point = { x: number; y: number };
export type Tone = "teal" | "azure" | "blend";
export type LayoutName = "desktop" | "tablet" | "mobile";

export type Layout = {
  viewBox: string;
  /** x positions of the left, centre and right columns. */
  columns: [number, number, number];
  topY: number;
  bottomY: number;
  /** y of the horizontal "bus" each side path travels along. */
  busTop: number;
  busBottom: number;
  stroke: number;
  labelSize: number;
  glow: boolean;
};

export type Connection = {
  id: string;
  label: string;
  tone: Tone;
  side: "top" | "bottom";
  align: "start" | "middle" | "end";
  node: Point;
  /** Point on (inside) the cloud where the path originates. */
  origin: Point;
  /** Drawn from the node towards the cloud, so a 0→1 reveal starts at the endpoint. */
  d: string;
  stub?: { d: string; dot: Point };
};

export const NODE_RADIUS = 22;
const CORNER = 30;

/** Custom cloud silhouette, centred on (600, 293). */
export const CLOUD_PATH =
  "M515 382C478 382 450 356 450 322C450 291 473 267 504 263C514 229 550 204 594 204C635 204 668 229 680 262C684 261.4 687 261 691 261C724 261 750 288 750 322C750 356 722 382 688 382Z";

export const CLOUD_CENTER: Point = { x: 600, y: 300 };

export const LAYOUTS: Record<LayoutName, Layout> = {
  desktop: {
    viewBox: "0 0 1200 620",
    columns: [230, 600, 970],
    topY: 78,
    bottomY: 540,
    busTop: 172,
    busBottom: 462,
    stroke: 1.5,
    labelSize: 13,
    glow: true,
  },
  tablet: {
    viewBox: "130 0 940 620",
    columns: [262, 600, 938],
    topY: 78,
    bottomY: 540,
    busTop: 172,
    busBottom: 462,
    stroke: 1.7,
    labelSize: 15,
    glow: true,
  },
  mobile: {
    viewBox: "290 14 620 592",
    columns: [346, 600, 854],
    topY: 84,
    bottomY: 534,
    busTop: 168,
    busBottom: 458,
    stroke: 2.4,
    labelSize: 21,
    glow: false,
  },
};

const ORIGINS = {
  top: [
    { x: 506, y: 288 },
    { x: 600, y: 232 },
    { x: 694, y: 288 },
  ],
  bottom: [
    { x: 532, y: 372 },
    { x: 600, y: 372 },
    { x: 668, y: 372 },
  ],
} satisfies Record<"top" | "bottom", Point[]>;

const NODES = {
  top: [
    { id: "anomaly", label: "Anomaly detection", tone: "teal" },
    { id: "incident", label: "Incident analysis", tone: "blend" },
    { id: "scaling", label: "Event-aware scaling", tone: "azure" },
  ],
  bottom: [
    { id: "quantum", label: "Quantum readiness", tone: "teal" },
    { id: "gate", label: "Code safety gate", tone: "blend" },
    { id: "runtime", label: "Runtime security", tone: "azure" },
  ],
} as const;

const ALIGN = ["start", "middle", "end"] as const;

function toward(from: Point, to: Point, distance: number): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const step = Math.min(distance, length / 2);
  return { x: from.x + (dx / length) * step, y: from.y + (dy / length) * step };
}

/** Orthogonal polyline with every corner replaced by a smooth quadratic bend. */
function roundedPath(points: Point[], radius: number): string {
  const fmt = (p: Point) => `${+p.x.toFixed(2)} ${+p.y.toFixed(2)}`;
  let d = `M${fmt(points[0])}`;
  for (let i = 1; i < points.length - 1; i++) {
    const corner = points[i];
    const enter = toward(corner, points[i - 1], radius);
    const exit = toward(corner, points[i + 1], radius);
    d += `L${fmt(enter)}Q${fmt(corner)} ${fmt(exit)}`;
  }
  return d + `L${fmt(points[points.length - 1])}`;
}

export function buildConnections(layout: Layout): Connection[] {
  return (["top", "bottom"] as const).flatMap((side) =>
    NODES[side].map((meta, i) => {
      const origin = ORIGINS[side][i];
      const node = { x: layout.columns[i], y: side === "top" ? layout.topY : layout.bottomY };
      const bus = side === "top" ? layout.busTop : layout.busBottom;
      const outward = side === "top" ? -1 : 1;
      const end = { x: node.x, y: node.y - outward * NODE_RADIUS };

      const points =
        Math.abs(node.x - origin.x) < 1
          ? [origin, end]
          : [origin, { x: origin.x, y: bus }, { x: node.x, y: bus }, end];

      // A short branch off the bus, ending in a small junction dot.
      let stub: Connection["stub"];
      if (points.length > 2) {
        const x = Math.round(origin.x + (node.x - origin.x) * 0.55);
        const dot = { x, y: bus + outward * 30 };
        stub = { d: `M${x} ${bus}V${dot.y}`, dot };
      }

      return {
        ...meta,
        side,
        align: ALIGN[i],
        node,
        origin,
        d: roundedPath([...points].reverse(), CORNER),
        stub,
      };
    }),
  );
}
