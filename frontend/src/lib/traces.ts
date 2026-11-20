/**
 * Geometry for the landing network: thin traces radiating from the cloud in every direction
 * and running off the edge of the screen.
 *
 * Coordinates are centred on (0, 0) — the middle of the viewport — and the SVG
 * uses a 1600 × 900 viewBox with `slice`, so the composition always fills the screen.
 */

export type Point = { x: number; y: number };

export type Trace = {
  id: string;
  d: string;
  /** Lines on the axes are the main ones; the rest are finer. */
  main: boolean;
  delay: number;
};

export const VIEW = { w: 1600, h: 900 };

export const CLOUD_CENTER: Point = { x: 0, y: -50 };

/** The BCSS logo (see lib/logo.ts) centred on CLOUD_CENTER, about 230 units wide. */
const LOGO_SCALE = 0.48;
export const LOGO_TRANSFORM = `translate(${CLOUD_CENTER.x} ${CLOUD_CENTER.y}) scale(${LOGO_SCALE}) translate(-515 -272)`;

/** The typed title sits below the cloud; traces pass underneath it. */
export const TITLE_Y = 40;

const COUNT = 32;
const CORNER = 22;
/**
 * Radial run before a trace turns parallel to the nearest axis, by how many steps the
 * trace sits from that axis. Growing with the step keeps the parallel runs nested, so
 * no two traces cross.
 */
const RADIAL = [0, 60, 85, 110];
/** Far enough out to be off-screen at any aspect ratio. */
const OFF = { x: 1300, y: 900 };

function toward(from: Point, to: Point, distance: number): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const step = Math.min(distance, length / 2);
  return { x: from.x + (dx / length) * step, y: from.y + (dy / length) * step };
}

/** Polyline with every corner replaced by a smooth quadratic bend. */
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

/**
 * Traces every 11.25°, skipping the four diagonals. Those on the axes run straight;
 * the rest leave radially, then turn parallel to the nearest axis.
 */
export function buildTraces(): Trace[] {
  const indices = Array.from({ length: COUNT }, (_, i) => i).filter((i) => i % 8 !== 4);
  return indices.map((i) => {
    const a = (i / COUNT) * Math.PI * 2;
    const dir = { x: Math.cos(a), y: Math.sin(a) };
    const start = { x: CLOUD_CENTER.x + dir.x * 70, y: CLOUD_CENTER.y + dir.y * 38 };
    const main = i % 4 === 0;

    let points: Point[];
    if (main) {
      // Straight on until the nearer of the two off-screen bounds.
      const t = Math.min(dir.x ? OFF.x / Math.abs(dir.x) : Infinity, dir.y ? OFF.y / Math.abs(dir.y) : Infinity);
      points = [start, { x: start.x + dir.x * t, y: start.y + dir.y * t }];
    } else {
      const step = i % 8 < 4 ? i % 8 : 8 - (i % 8);
      const radial = RADIAL[step];
      const bend = { x: start.x + dir.x * radial, y: start.y + dir.y * radial };
      const horizontal = Math.abs(dir.x) > Math.abs(dir.y);
      const end = horizontal
        ? { x: Math.sign(dir.x) * OFF.x, y: bend.y }
        : { x: bend.x, y: Math.sign(dir.y) * OFF.y };
      points = [start, bend, end];
    }

    return {
      id: `t${i}`,
      d: roundedPath(points, CORNER),
      main,
      delay: 0, // every trace grows at once
    };
  });
}
