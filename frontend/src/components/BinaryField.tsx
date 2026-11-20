import { useEffect, useRef } from "react";

const CELL = 30; // px between digits
const FONT = 19; // px
const RADIUS = 190; // px of the reveal around the pointer
const BASE_ALPHA = 0.06;
const PEAK_ALPHA = 0.75;
const FLIP_MS = 110;
const FLIP_SHARE = 0.05;

/**
 * Full-screen field of binary digits that keep flipping. Nearly invisible on its own;
 * the area around the pointer reveals it. It fades out as the page scrolls past the hero.
 */
export function BinaryField() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current!;
    const ctx = el.getContext("2d")!;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const reveal = window.matchMedia("(pointer: fine)").matches;

    let cols = 0;
    let rows = 0;
    let bits = new Uint8Array(0);
    const target = { x: -1e4, y: -1e4 };
    const pointer = { ...target };
    let frame = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      el.width = window.innerWidth * dpr;
      el.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = `${FONT}px "Share Tech Mono", ui-monospace, monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      cols = Math.ceil(window.innerWidth / CELL) + 1;
      rows = Math.ceil(window.innerHeight / CELL) + 1;
      bits = Uint8Array.from({ length: cols * rows }, () => (Math.random() < 0.5 ? 0 : 1));
    };

    const draw = () => {
      pointer.x += (target.x - pointer.x) * 0.18;
      pointer.y += (target.y - pointer.y) * 0.18;
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      const h = window.innerHeight;
      const fade = Math.min(1, Math.max(0, 1 - (window.scrollY - h * 0.3) / (h * 0.45)));
      el.style.opacity = String(fade);
      if (fade === 0) {
        frame = requestAnimationFrame(draw);
        return;
      }
      for (let r = 0; r < rows; r++) {
        const y = r * CELL + CELL / 2;
        for (let c = 0; c < cols; c++) {
          const x = c * CELL + CELL / 2;
          const d = Math.hypot(x - pointer.x, y - pointer.y);
          const t = d < RADIUS ? 1 - d / RADIUS : 0;
          const lit = t * t * (3 - 2 * t); // smoothstep
          const alpha = BASE_ALPHA + lit * PEAK_ALPHA;
          ctx.fillStyle = lit > 0 ? `rgba(111, 228, 214, ${alpha})` : `rgba(150, 190, 255, ${BASE_ALPHA})`;
          ctx.fillText(bits[r * cols + c] ? "1" : "0", x, y);
        }
      }
      frame = requestAnimationFrame(draw);
    };

    const flip = still
      ? 0
      : window.setInterval(() => {
          const n = Math.ceil(bits.length * FLIP_SHARE);
          for (let i = 0; i < n; i++) bits[(Math.random() * bits.length) | 0] ^= 1;
        }, FLIP_MS);

    const onMove = (e: PointerEvent) => {
      if (target.x < -1e3) {
        pointer.x = e.clientX;
        pointer.y = e.clientY;
      }
      target.x = e.clientX;
      target.y = e.clientY;
    };
    const onLeave = () => {
      target.x = -1e4;
      target.y = -1e4;
      pointer.x = target.x;
      pointer.y = target.y;
    };

    resize();
    document.fonts?.ready.then(resize);
    window.addEventListener("resize", resize);
    if (reveal) {
      window.addEventListener("pointermove", onMove, { passive: true });
      document.documentElement.addEventListener("pointerleave", onLeave);
    }
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      clearInterval(flip);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return <canvas ref={canvas} className="pointer-events-none fixed inset-0 z-0 h-full w-full" aria-hidden="true" />;
}
