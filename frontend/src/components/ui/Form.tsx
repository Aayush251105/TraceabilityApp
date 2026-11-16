import type { InputHTMLAttributes, ReactNode } from "react";

/** Small segmented control (tabs inside a grey track). */
export function Segmented<T extends string>({ options, value, onChange, label, size = "sm" }: {
  options: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-0.5 rounded-md border border-border bg-subtle p-0.5">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(o.id)}
            className={`flex cursor-pointer items-center gap-1.5 rounded border-0 px-2.5 text-xs font-medium ${size === "md" ? "h-[26px]" : "h-6"}`}
            style={{
              background: on ? "var(--panel)" : "transparent",
              color: on ? "var(--fg)" : "var(--fg2)",
              boxShadow: on ? "0 1px 2px rgba(0,0,0,.08)" : "none",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Label above a control, with an optional quiet hint after the label. */
export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-fg2">
      <span>
        {label} {hint && <span className="font-normal text-fg3">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

export function TextInput({ invalid, mono, className = "", ...rest }: InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
  mono?: boolean;
}) {
  return (
    <input
      {...rest}
      aria-invalid={invalid || undefined}
      className={
        `h-[34px] rounded-md border bg-panel px-2.5 text-[13px] text-fg outline-none placeholder:text-fg3/60 focus:border-accent ` +
        `${mono ? "font-mono" : ""} ${className}`
      }
      style={{ borderColor: invalid ? "var(--bad)" : "var(--border-strong)" }}
    />
  );
}

/** Bordered panel with a title row (title, subtitle, optional control on the right). */
export function Panel({ title, subtitle, action, children, id }: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col rounded-lg border border-border bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5">
        <div className="min-w-0">
          <h2 id={id} className="m-0 text-sm font-semibold">{title}</h2>
          {subtitle && <div className="text-xs text-fg3">{subtitle}</div>}
        </div>
        {action}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">{children}</div>
    </section>
  );
}

type Tone = "error" | "warn" | "ok" | "info";

/** Inline message: error (round "!"), warning (triangle), success (✓), info (plain box). */
export function Alert({ tone, title, children, boxed = tone === "warn" || tone === "info" }: {
  tone: Tone;
  title?: ReactNode;
  children?: ReactNode;
  boxed?: boolean;
}) {
  const colour = { error: "var(--bad)", warn: "var(--part)", ok: "var(--ok)", info: "var(--fg3)" }[tone];
  const bg = { error: "var(--bad-bg)", warn: "var(--part-bg)", ok: "var(--ok-bg)", info: "var(--subtle)" }[tone];
  const icon =
    tone === "warn" ? (
      <span
        aria-hidden="true"
        className="mt-0.5 h-0 w-0 flex-none"
        style={{ borderLeft: "8px solid transparent", borderRight: "8px solid transparent", borderBottom: `14px solid ${colour}` }}
      />
    ) : tone === "info" ? null : (
      <span
        aria-hidden="true"
        className="mt-0.5 h-4 w-4 flex-none rounded-full text-center font-mono text-[11px] leading-4 font-bold"
        style={{ background: colour, color: "var(--panel)" }}
      >
        {tone === "ok" ? "✓" : "!"}
      </span>
    );
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex gap-2.5 text-[13px] ${boxed ? "rounded-md border p-3" : ""}`}
      style={boxed ? { borderColor: tone === "info" ? "transparent" : colour, background: bg, color: tone === "info" ? "var(--fg3)" : "var(--fg)" } : undefined}
    >
      {icon}
      <span>
        {title && <strong className="font-semibold">{title} </strong>}
        {children}
      </span>
    </div>
  );
}
