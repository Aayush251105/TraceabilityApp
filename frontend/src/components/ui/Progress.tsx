import { clock } from "../../lib/format";

interface ProgressBarProps {
  /** 0..1; omit for an indeterminate bar (estimating) */
  value?: number | null;
  color?: string;
  height?: number;
  label?: string;
}

export function ProgressBar({ value, color = "var(--accent)", height = 6, label }: ProgressBarProps) {
  const indeterminate = value == null;
  const pct = indeterminate ? 0 : Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : pct}
      className="overflow-hidden bg-hover"
      style={{ height, borderRadius: height / 2 }}
    >
      {indeterminate ? (
        <div className="h-full w-2/5 opacity-70" style={{ background: color, animation: "tlInd 1.6s ease-in-out infinite" }} />
      ) : (
        <div className="h-full transition-[width] duration-[250ms] ease-out" style={{ width: `${pct}%`, background: color }} />
      )}
    </div>
  );
}

/** Large mono timer: label above, value below. */
export function Timer({ label, seconds, text, muted, paused }: {
  label: string;
  seconds?: number | null;
  /** shown instead of a clock (e.g. "~23 min") */
  text?: string;
  muted?: boolean;
  paused?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs" style={{ color: paused ? "var(--rev)" : "var(--fg3)" }}>
        {paused && (
          <span aria-hidden="true" className="inline-flex gap-0.5">
            <span className="h-2.5 w-[3px]" style={{ background: "var(--rev)" }} />
            <span className="h-2.5 w-[3px]" style={{ background: "var(--rev)" }} />
          </span>
        )}
        {label}
      </div>
      <div
        className="font-mono text-2xl leading-tight font-medium tracking-[-0.02em]"
        style={{ color: paused ? "var(--fg3)" : muted ? "var(--fg2)" : "var(--fg)" }}
      >
        {text ?? clock(seconds)}
      </div>
    </div>
  );
}
