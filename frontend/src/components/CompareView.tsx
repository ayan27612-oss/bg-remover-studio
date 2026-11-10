import { useRef, useState } from "react";
import { ChevronsLeftRight } from "lucide-react";

interface CompareViewProps {
  originalUrl: string;
  processedUrl: string;
  alt?: string;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export default function CompareView({
  originalUrl,
  processedUrl,
  alt = "Background removal result",
}: CompareViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(50);
  const [dragging, setDragging] = useState(false);

  const move = (clientX: number) => {
    const element = containerRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    setPosition(clamp(((clientX - rect.left) / rect.width) * 100, 0, 100));
  };

  return (
    <div
      ref={containerRef}
      className="relative h-[clamp(300px,58vh,660px)] w-full touch-none select-none overflow-hidden rounded-2xl border border-line bg-panel2"
      onPointerDown={(event) => {
        setDragging(true);
        event.currentTarget.setPointerCapture(event.pointerId);
        move(event.clientX);
      }}
      onPointerMove={(event) => {
        if (dragging) move(event.clientX);
      }}
      onPointerUp={(event) => {
        setDragging(false);
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={() => setDragging(false)}
    >
      <img
        src={originalUrl}
        alt={`${alt} — original`}
        className="absolute inset-0 h-full w-full bg-panel2 object-contain"
        draggable={false}
      />

      <div
        className="checker absolute inset-0"
        style={{ clipPath: `inset(0 0 0 ${position}%)` }}
      >
        <img
          src={processedUrl}
          alt={`${alt} — background removed`}
          className="absolute inset-0 h-full w-full object-contain"
          draggable={false}
        />
      </div>

      <span className="pointer-events-none absolute left-3 top-3 rounded-full border border-line bg-panel/80 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-muted backdrop-blur">
        Original
      </span>
      <span className="pointer-events-none absolute right-3 top-3 rounded-full border border-line bg-panel/80 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-muted backdrop-blur">
        Cutout
      </span>

      <div
        className="pointer-events-none absolute inset-y-0 z-10 w-px bg-ink/60"
        style={{ left: `${position}%` }}
      />
      <div
        role="slider"
        tabIndex={0}
        aria-label="Comparison position"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(position)}
        className="absolute top-1/2 z-20 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize items-center justify-center rounded-full border border-line bg-panel text-ink shadow-sm transition hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/25"
        style={{ left: `${position}%` }}
        onPointerDown={(event) => {
          event.stopPropagation();
          setDragging(true);
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (dragging) move(event.clientX);
        }}
        onPointerUp={(event) => {
          setDragging(false);
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            setPosition((value) => clamp(value - 2, 0, 100));
          } else if (event.key === "ArrowRight") {
            event.preventDefault();
            setPosition((value) => clamp(value + 2, 0, 100));
          } else if (event.key === "Home") {
            event.preventDefault();
            setPosition(0);
          } else if (event.key === "End") {
            event.preventDefault();
            setPosition(100);
          }
        }}
      >
        <ChevronsLeftRight className="h-4 w-4" strokeWidth={1.75} />
      </div>
    </div>
  );
}
