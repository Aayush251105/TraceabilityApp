import type { ReactNode } from "react";

import { verdictMeta } from "../../lib/status";
import { StatusText } from "./Status";

export interface Citation {
  label: string; // "lending.py:36-37"
  onClick?: () => void;
}

export interface Discarded {
  label: string;
  reason: string;
}

/** One claim of a requirement: verdict, why, accepted citations, discarded evidence. */
export function ClaimItem({ tag, text, verdict, rationale, citations = [], discarded = [], active, onSelect }: {
  tag: string;
  text: string;
  verdict: string;
  rationale?: string;
  citations?: Citation[];
  discarded?: Discarded[];
  active?: boolean;
  onSelect?: () => void;
}) {
  const meta = verdictMeta(verdict);
  return (
    <div
      onClick={onSelect}
      className={`grid gap-2 rounded-lg border bg-panel px-4 py-3 ${onSelect ? "cursor-pointer" : ""}`}
      style={{
        gridTemplateColumns: "28px minmax(0,1fr)",
        borderColor: active ? "var(--accent)" : "var(--border)",
        boxShadow: active ? "0 0 0 3px var(--accent-bg)" : "none",
      }}
    >
      <span className="font-mono text-[11px] leading-5 font-medium text-fg3">{tag}</span>
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="text-sm font-medium">{text}</div>
        <StatusText meta={meta} />
        {rationale && <div className="text-[13px] text-fg2">{rationale}</div>}
        {citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {citations.map((c) => (
              <button
                key={c.label}
                onClick={(e) => {
                  e.stopPropagation();
                  c.onClick?.();
                }}
                className="h-6 cursor-pointer rounded border border-border-strong bg-ok-bg px-2 font-mono text-xs leading-[22px] font-medium hover:border-fg3"
              >
                {c.label}
              </button>
            ))}
          </div>
        )}
        {discarded.map((d) => (
          <div key={d.label + d.reason} className="text-xs text-fg3">
            <span className="font-mono line-through">{d.label}</span> Discarded evidence: {d.reason}
          </div>
        ))}
      </div>
    </div>
  );
}

export type NodeKind = "requirement" | "direct" | "supporting";

/** A node of the mapped subgraph. */
export function GraphNode({ kind, label, selected, hovered, width = 200, children }: {
  kind: NodeKind;
  label: string;
  selected?: boolean;
  hovered?: boolean;
  width?: number;
  children?: ReactNode;
}) {
  const req = kind === "requirement";
  const caption = `${kind.toUpperCase()}${selected ? " · SELECTED" : hovered ? " · HOVER" : ""}`;
  return (
    <span
      className="flex h-10 flex-col justify-center rounded-md border px-2.5"
      style={{
        width,
        borderColor: req ? "var(--accent)" : selected ? "var(--fg)" : "var(--border-strong)",
        background: req ? "var(--accent-bg)" : selected ? "var(--subtle)" : "var(--panel)",
        boxShadow: hovered ? "0 0 0 3px var(--hover)" : "none",
      }}
    >
      <span
        className="font-mono text-[9px] font-semibold tracking-[.05em]"
        style={{ color: req ? "var(--accent)" : selected ? "var(--fg2)" : "var(--fg3)" }}
      >
        {caption}
      </span>
      <span className="truncate font-mono text-xs font-medium">{label}</span>
      {children}
    </span>
  );
}
