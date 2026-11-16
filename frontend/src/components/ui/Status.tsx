import type { StatusMeta } from "../../lib/status";

/** The small shape inside a chip: circle for outcomes, square for states that need attention. */
export function Glyph({ meta, size = 12 }: { meta: StatusMeta; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block flex-none text-center"
      style={{
        width: size,
        height: size,
        borderRadius: meta.r,
        border: `1.5px solid ${meta.c}`,
        background: meta.ib,
        color: "var(--panel)",
        font: `700 ${Math.round(size * 0.58)}px/${size - 3}px sans-serif`,
      }}
    >
      {meta.g}
    </span>
  );
}

/** Verdict / state chip: colour + shape + label. */
export function StatusChip({ meta, label, className = "" }: { meta: StatusMeta; label?: string; className?: string }) {
  return (
    <span
      className={`inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded pr-2 pl-1.5 text-xs font-medium ${className}`}
      style={{ background: meta.b, color: meta.c }}
    >
      <Glyph meta={meta} />
      {label ?? meta.label}
    </span>
  );
}

/** Glyph + label without a background (inline in text, claim items). */
export function StatusText({ meta, label }: { meta: StatusMeta; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: meta.c }}>
      <Glyph meta={meta} />
      {label ?? meta.label}
    </span>
  );
}
