import type { StatusMeta } from "../../lib/status";

export interface CodeLine {
  n: number;
  text: string;
}

export interface LineHighlight {
  /** verdict colours of the claim that cites this line */
  meta: StatusMeta;
  /** marker shown on the first cited line, e.g. "C2" */
  mark?: string;
}

/** Source lines with real line numbers; cited lines get a coloured bar, tint and claim marker. */
export function CodeBlock({ lines, highlights = {}, maxHeight }: {
  lines: CodeLine[];
  highlights?: Record<number, LineHighlight>;
  maxHeight?: number;
}) {
  return (
    <div className="overflow-auto rounded-md border border-border bg-code-bg" style={{ maxHeight }}>
      <div className="min-w-max py-2">
        {lines.map((ln) => {
          const h = highlights[ln.n];
          return (
            <div
              key={ln.n}
              data-line={ln.n}
              className="grid h-[22px] items-center"
              style={{ gridTemplateColumns: "36px 40px auto", background: h ? h.meta.b : "transparent" }}
            >
              <span
                className="flex h-full items-center justify-center"
                style={{ borderLeft: `3px solid ${h ? h.meta.c : "transparent"}` }}
              >
                {h?.mark && (
                  <span
                    className="h-4 rounded-[3px] px-1 font-mono text-[10px] leading-4 font-semibold"
                    style={{ background: h.meta.c, color: "var(--panel)" }}
                  >
                    {h.mark}
                  </span>
                )}
              </span>
              <span className="pr-3.5 text-right font-mono text-xs text-fg3 select-none">{ln.n}</span>
              <code className="pr-5 font-mono text-[13px] leading-[22px] whitespace-pre text-fg">{ln.text || " "}</code>
            </div>
          );
        })}
      </div>
    </div>
  );
}
