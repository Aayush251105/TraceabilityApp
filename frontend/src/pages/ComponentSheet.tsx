import { useEffect, useState } from "react";

import { PageHeader } from "../components/layout/AppShell";
import { Button } from "../components/ui/Button";
import { CodeBlock, type LineHighlight } from "../components/ui/Code";
import { ProgressBar, Timer } from "../components/ui/Progress";
import { StatusChip } from "../components/ui/Status";
import { ClaimItem, GraphNode } from "../components/ui/Trace";
import { percent } from "../lib/format";
import { STAGE_STATES, VERDICT_ORDER, VERDICTS, type StageState } from "../lib/status";

const RUN_STATES: StageState[] = ["queued", "running", "done", "waiting", "failed"];

const CODE = [
  { n: 21, text: "    def checkout(self, member: Member, isbn: str) -> Loan:" },
  { n: 22, text: "        book = self.catalogue.find_by_isbn(isbn)" },
  { n: 23, text: "        if book is None:" },
  { n: 24, text: '            raise CheckoutError("Unknown ISBN")' },
  { n: 25, text: "        if not member.can_borrow():" },
  { n: 26, text: '            raise CheckoutError("Member cannot borrow")' },
];
const HIGHLIGHTS: Record<number, LineHighlight> = {
  22: { meta: VERDICTS.supported, mark: "C1" },
  23: { meta: VERDICTS.supported },
  24: { meta: VERDICTS.supported },
  25: { meta: VERDICTS.supported, mark: "C2" },
  26: { meta: VERDICTS.supported },
};

const ROWS = [
  { id: "FR-016", title: "Check out a book", v: "supported", claims: "4 / 4", bg: "transparent" },
  { id: "FR-034", title: "Renewal eligibility", v: "partially_supported", claims: "1 / 2", bg: "var(--subtle)" },
  { id: "FR-031", title: "Due-date email reminders", v: "not_supported_by_candidate", claims: "1 / 2", bg: "var(--accent-bg)" },
] as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="text-xs font-medium text-fg3">{title}</div>
      {children}
    </div>
  );
}

function Sheet({ theme, seconds, pct }: { theme: "light" | "dark"; seconds: number; pct: number }) {
  return (
    <div data-theme={theme} className="flex flex-col gap-7 rounded-[10px] border border-border bg-bg p-6 text-fg">
      <div className="font-mono text-[11px] font-medium tracking-[.06em] text-fg3">{theme.toUpperCase()}</div>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Primary</Button>
          <Button>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button disabled>Disabled</Button>
          <Button className="outline-2 outline-offset-2 outline-accent">Focus visible</Button>
        </div>
      </Section>

      <Section title="Verdict chips">
        <div className="flex flex-wrap gap-2">
          {VERDICT_ORDER.map((v) => (
            <StatusChip key={v} meta={VERDICTS[v]} />
          ))}
        </div>
        <div className="mt-1.5 text-xs font-medium text-fg3">Run and stage status</div>
        <div className="flex flex-wrap gap-2">
          {RUN_STATES.map((s) => (
            <StatusChip key={s} meta={{ ...STAGE_STATES[s], g: "" }} />
          ))}
        </div>
      </Section>

      <div className="grid grid-cols-2 gap-6">
        <Section title="Progress">
          <div>
            <div className="mb-1 flex justify-between text-xs">
              <span>Running</span>
              <span className="font-mono text-fg3">{percent(pct)}</span>
            </div>
            <ProgressBar value={pct} label="Running" />
          </div>
          <div>
            <div className="mb-1 text-xs">Estimating (indeterminate)</div>
            <ProgressBar label="Estimating" />
          </div>
          <div>
            <div className="mb-1 text-xs text-rev">Paused for review</div>
            <ProgressBar value={0.5} color="var(--rev)" label="Paused for review" />
          </div>
          <div>
            <div className="mb-1 text-xs text-bad">Failed at 56%</div>
            <ProgressBar value={0.56} color="var(--bad)" label="Failed" />
          </div>
        </Section>
        <Section title="Timer">
          <div className="flex gap-6">
            <Timer label="Elapsed" seconds={seconds} />
            <Timer label="Remaining" text="~23 min" muted />
          </div>
          <Timer label="Paused for review" seconds={1872} paused />
        </Section>
      </div>

      <Section title="Table rows · default, hover, selected">
        <div className="overflow-hidden rounded-lg border border-border bg-panel">
          <div
            className="grid h-8 items-center gap-3 border-b border-border px-3 text-xs font-medium text-fg3"
            style={{ gridTemplateColumns: "80px minmax(0,1fr) 200px 56px" }}
          >
            <span>ID</span>
            <span>Title</span>
            <span>Verdict</span>
            <span>Claims</span>
          </div>
          {ROWS.map((r) => (
            <div
              key={r.id}
              className="grid h-11 items-center gap-3 border-b border-border px-3 text-[13px] last:border-b-0"
              style={{ gridTemplateColumns: "80px minmax(0,1fr) 200px 56px", background: r.bg }}
            >
              <span className="font-mono text-xs font-medium">{r.id}</span>
              <span className="truncate">{r.title}</span>
              <span>
                <StatusChip meta={VERDICTS[r.v]} />
              </span>
              <span className="font-mono text-xs text-fg2">{r.claims}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Code block · highlighted citation lines">
        <CodeBlock lines={CODE} highlights={HIGHLIGHTS} />
      </Section>

      <div className="grid grid-cols-2 gap-6">
        <Section title="Claim item">
          <ClaimItem
            tag="C2"
            text="Members with outstanding fines cannot renew."
            verdict="not_supported_by_candidate"
            rationale="renew() never reads Member.fines_due."
            citations={[{ label: "lending.py:36-37" }]}
            discarded={[{ label: "models.py:15", reason: "defined but never read" }]}
          />
        </Section>
        <Section title="Graph nodes · requirement, direct, supporting, hover">
          <div className="flex flex-col gap-2">
            <GraphNode kind="requirement" label="FR-016 Check out a book" />
            <GraphNode kind="direct" label="LendingService.checkout" selected />
            <GraphNode kind="supporting" label="Member.can_borrow" />
            <GraphNode kind="supporting" label="Book.checkout_copy" hovered />
          </div>
        </Section>
      </div>
    </div>
  );
}

export function ComponentSheet() {
  const [t, setT] = useState(761);
  const [p, setP] = useState(0.44);
  useEffect(() => {
    const iv = setInterval(() => {
      setT((x) => x + 1);
      setP((x) => (x >= 0.96 ? 0.12 : x + 0.02));
    }, 1000);
    return () => clearInterval(iv);
  }, []);

  return (
    <>
      <PageHeader
        title="Component sheet"
        subtitle="IBM Plex Sans + Mono · type scale 12/14/16/20/24/32 · 8 px grid · one accent · status = colour + shape + label"
      />
      <div className="grid gap-6 px-8 pt-6 pb-12" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(560px,1fr))" }}>
        <Sheet theme="light" seconds={t} pct={p} />
        <Sheet theme="dark" seconds={t} pct={p} />
      </div>
    </>
  );
}
