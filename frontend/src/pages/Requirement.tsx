import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useResults, useRun } from "../api/hooks";
import type { RequirementDetail } from "../api/types";
import { Button } from "../components/ui/Button";
import { Alert } from "../components/ui/Form";
import { Glyph } from "../components/ui/Status";
import { dateTime } from "../lib/format";
import {
  citationLabel, claimMeta, codeSpans, discardedLabel, GRAPH_MIN_W, INCOMPLETE_PREFIX, layoutGraph, lineMarks, tagMap, whyRows,
} from "../lib/requirement";
import { locationLabel } from "../lib/review";
import { typeLabel } from "../lib/results";
import { VERDICT_ORDER, VERDICTS, verdictMeta } from "../lib/status";

function useDetail(runId: number, rid: string) {
  return useQuery({
    queryKey: ["requirement", runId, rid],
    queryFn: () => api.get<RequirementDetail>(`/api/runs/${runId}/requirements/${encodeURIComponent(rid)}`),
  });
}

/** Text with `identifiers` shown as inline code. */
function Prose({ text }: { text: string }) {
  return (
    <>
      {codeSpans(text).map((p, i) => (p.code
        ? <code key={i} className="rounded-[3px] bg-subtle px-1 font-mono text-[0.92em] text-fg">{p.text}</code>
        : <span key={i}>{p.text}</span>))}
    </>
  );
}

/** Width of an element, kept up to date (for laying out the subgraph). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  });
  return [ref, width] as const;
}

const Section = ({ title, aside, children, id }: { title: string; aside?: React.ReactNode; children: React.ReactNode; id: string }) => (
  <section aria-labelledby={id} className="rounded-lg border border-border bg-panel">
    <div className="flex items-baseline justify-between gap-3 border-b border-border px-4 py-3">
      <h2 id={id} className="m-0 text-sm font-semibold">{title}</h2>
      {aside && <span className="text-xs text-fg3">{aside}</span>}
    </div>
    {children}
  </section>
);

export function Requirement() {
  const { runId, requirementId } = useParams();
  const id = Number(runId);
  const rid = decodeURIComponent(requirementId ?? "");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: run } = useRun(id);
  const { data: results } = useResults(id);
  const { data: d, isLoading, error } = useDetail(id, rid);

  const [comp, setComp] = useState<string | null>(null);
  const [activeClaim, setActiveClaim] = useState<number | null>(null);
  const [pulse, setPulse] = useState<{ a: number; b: number; flip: boolean } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [whyOpen, setWhyOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [ovVerdict, setOvVerdict] = useState<string>("supported");
  const [ovNote, setOvNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const codeBox = useRef<HTMLDivElement>(null);
  const codePanel = useRef<HTMLElement>(null);
  const [graphBox, graphWidth] = useWidth<HTMLDivElement>();

  // A new requirement: reset the page state.
  useEffect(() => {
    setComp(null);
    setActiveClaim(null);
    setPulse(null);
    setOverrideOpen(false);
    setOvNote("");
    setProblem(null);
  }, [rid]);

  const ids = results?.requirements.map((r) => r.requirement_id) ?? [];
  const at = ids.indexOf(rid);
  const go = (delta: number) => {
    const next = ids[at + delta];
    if (next) navigate(`/runs/${id}/requirements/${encodeURIComponent(next)}`);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (e.key === "ArrowLeft" && e.altKey) go(-1);
      if (e.key === "ArrowRight" && e.altKey) go(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const graph = useMemo(() => (d ? layoutGraph(d, graphWidth - 32) : null), [d, graphWidth]);
  const tags = useMemo(() => (d ? tagMap(d.claims) : {}), [d]);

  if (isLoading) return <div className="px-8 py-6 text-[13px] text-fg3">Loading requirement…</div>;
  if (error || !d) {
    return (
      <div className="px-8 py-6">
        <Alert tone="error" title="Requirement not found.">{(error as ApiError)?.message} <Link to={`/runs/${id}/results`}>Back to results</Link></Alert>
      </div>
    );
  }

  const req = d.requirement;
  const current = d.components.find((c) => c.component_id === comp) ?? d.components[0] ?? null;
  const marks = current ? lineMarks(d.claims, current.component_id, activeClaim) : {};
  const verdict = verdictMeta(d.verdict.status);
  const supportedClaims = d.claims.filter((c) => c.verdict === "supported").length;
  const human = d.verdict.source === "human";
  const accepted = human && d.verdict.status === d.verdict.machine;
  const summary = d.verification?.rationale.replace(INCOMPLETE_PREFIX, "").trim();
  const canVerify = run?.status === "completed" && !run.active;

  const refresh = () => Promise.all([
    qc.invalidateQueries({ queryKey: ["requirement", id, rid] }),
    qc.invalidateQueries({ queryKey: ["results", id] }),
  ]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await fn();
      await refresh();
      setToast(done);
      setTimeout(() => setToast(null), 5000);
      return true;
    } catch (e) {
      setProblem((e as ApiError).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const override = (status: string, note: string) =>
    api.json("POST", `/api/runs/${id}/requirements/${encodeURIComponent(rid)}/override`, { status, note });

  const goCite = (ci: number, componentId: string, a: number, b: number) => {
    setComp(componentId);
    setActiveClaim(ci);
    setPulse((p) => ({ a, b, flip: !p?.flip }));
    requestAnimationFrame(() => {
      const target = d.components.find((c) => c.component_id === componentId);
      if (codeBox.current && target) codeBox.current.scrollTop = Math.max(0, (a - target.start_line) * 22 - 40);
      const top = codePanel.current?.getBoundingClientRect().top;
      if (top != null && (top < 0 || top > window.innerHeight * 0.6)) window.scrollBy({ top: top - 16, behavior: "smooth" });
    });
  };

  const reverify = () => act(async () => {
    await api.json("POST", `/api/runs/${id}/verify`, { requirement_ids: [rid] });
    await qc.invalidateQueries({ queryKey: keys.run(id) });
  }, `Re-verifying ${rid}. The verdict updates when it finishes.`);

  const why = whyRows(d);
  const location = locationLabel(req.location);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <header className="flex flex-col gap-3 border-b border-border bg-panel px-8 pt-4 pb-5">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-fg3">
            <Link to={`/runs/${id}/results`} className="text-fg3">Run #{id} results</Link> / {rid}
          </div>
          <div className="flex gap-1">
            <Button size="sm" onClick={() => go(-1)} disabled={at <= 0} aria-label="Previous requirement" title="Alt + ←">← Prev</Button>
            <Button size="sm" onClick={() => go(1)} disabled={at < 0 || at >= ids.length - 1} aria-label="Next requirement" title="Alt + →">Next →</Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-xl font-medium text-fg2">{req.requirement_id}</span>
          <h1 className="m-0 text-2xl font-semibold tracking-[-0.015em]">{req.title}</h1>
          <span className="inline-flex h-[26px] items-center gap-1.5 rounded pr-2.5 pl-2 text-[13px] font-medium" style={{ background: verdict.b, color: verdict.c }}>
            <Glyph meta={verdict} size={14} />{verdict.label}
          </span>
          {d.claims.length > 0 && <span className="font-mono text-xs text-fg3">{supportedClaims} / {d.claims.length} claims verified</span>}
          {human && (
            <span className="text-xs text-fg3">
              {accepted ? "Accepted by a reviewer" : `Overridden by a reviewer · verifier said ${verdictMeta(d.verdict.machine).label}`}
            </span>
          )}
        </div>
        <div className="grid items-start gap-6" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
          <p className="m-0 max-w-[820px] text-base leading-relaxed text-pretty whitespace-pre-line">{req.raw_text}</p>
          <div className="text-right text-xs whitespace-nowrap text-fg3">
            <div>Source</div>
            <div className="font-mono text-fg2">{run?.srs_filename ?? "SRS"}{location ? ` · ${location}` : ""}</div>
            <div>{typeLabel(req.type)}{req.subtype && req.subtype !== "general" ? ` · ${req.subtype}` : ""}</div>
          </div>
        </div>
        {d.flags.map((f) => (
          <div key={f.code} role="note" className="flex items-center gap-2 text-[13px]"
            style={{ color: f.level === "error" ? "var(--bad)" : f.level === "warn" ? "var(--part)" : "var(--fg2)" }}>
            {f.level !== "info" && <span aria-hidden="true" className="h-0 w-0" style={{ borderLeft: "7px solid transparent", borderRight: "7px solid transparent", borderBottom: "12px solid currentColor" }} />}
            <strong className="font-semibold">{f.label}.</strong>
            {f.code === "incomplete_text" && <span className="text-fg2">The requirement introduces a list or condition that was not captured; missing parts cannot be verified.</span>}
            {f.code === "edited" && req.review.original_raw_text && <span className="text-fg2">Original: “{req.review.original_raw_text}”</span>}
          </div>
        ))}
        {summary && (
          <div className="text-[13px] text-fg2"><span className="font-medium text-fg">Verifier summary:</span> <Prose text={summary} /></div>
        )}
      </header>

      <div className="grid items-start gap-4 px-8 pt-4 pb-12" style={{ gridTemplateColumns: "minmax(320px,400px) minmax(0,1fr)" }}>
        {/* Left column */}
        <div className="sticky top-4 flex flex-col gap-4">
          {problem && <Alert tone="error">{problem}</Alert>}
          <Section id="claims-h" title="Claims" aside={d.claims.length ? "Click a citation to see the lines" : undefined}>
            {d.claims.length === 0 ? (
              <div className="px-4 py-3 text-[13px] text-fg3">
                {d.verdict.status === "not_found" ? "The search found no candidate code, so no claims were checked." : "Not verified yet."}
              </div>
            ) : (
              <ol className="m-0 list-none p-0">
                {d.claims.map((c, ci) => {
                  const m = claimMeta(c.verdict);
                  const on = activeClaim === ci;
                  return (
                    <li key={ci} className="border-b border-border px-4 py-3 transition-colors duration-150 last:border-b-0"
                      style={{ background: on ? "var(--subtle)" : "transparent" }}>
                      <div className="grid gap-2" style={{ gridTemplateColumns: "28px minmax(0,1fr)" }}>
                        <button onClick={() => setActiveClaim(on ? null : ci)} className="cursor-pointer self-start border-0 bg-transparent p-0 text-left font-mono text-[11px] leading-5 font-medium text-fg3">
                          C{ci + 1}
                        </button>
                        <div className="flex min-w-0 flex-col gap-1.5">
                          <div className="text-sm font-medium text-pretty">{c.text}</div>
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: m.c }}><Glyph meta={m} />{m.label}</span>
                          {c.rationale && <div className="text-[13px] text-pretty text-fg2"><Prose text={c.rationale} /></div>}
                          {c.evidence.length > 0 ? (
                            <div className="flex flex-wrap gap-1.5">
                              {c.evidence.map((e, k) => (
                                <button key={k} onClick={() => goCite(ci, e.component_id, e.start_line, e.end_line)}
                                  title={e.quote ? `“${e.quote}”` : undefined}
                                  className="h-6 cursor-pointer rounded border px-2 font-mono text-xs font-medium text-fg transition-colors duration-150 hover:border-fg3"
                                  style={{ borderColor: on ? m.c : "var(--border-strong)", background: m.b }}>
                                  {citationLabel(e.path, e.start_line, e.end_line)}
                                </button>
                              ))}
                            </div>
                          ) : (
                            <div className="text-xs text-fg3">No supporting lines cited.</div>
                          )}
                          {c.rejected.map((r, k) => (
                            <div key={k} className="flex gap-2 text-xs text-fg3">
                              <span className="font-mono whitespace-nowrap line-through">{discardedLabel(r.reference, tags, d.components)}</span>
                              <span>Discarded evidence: <Prose text={r.reason.replace(/^C\d+:\s*/, "")} /></span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </Section>

          <Section id="act-h" title="Your decision">
            <div className="flex flex-col gap-2.5 px-4 py-3">
              <div className="flex flex-wrap gap-2">
                {d.verdict.machine && (
                  accepted ? (
                    <Button onClick={() => act(() => override("cleared", "Acceptance withdrawn"), "Acceptance withdrawn")} disabled={busy}
                      className="border-ok bg-ok-bg text-ok">✓ Accepted</Button>
                  ) : !human && (
                    <Button variant="primary" disabled={busy} onClick={() => act(() => override(d.verdict.machine!, "Accepted the verifier's verdict"), "Verdict accepted")}>
                      Accept verdict
                    </Button>
                  )
                )}
                <Button onClick={() => setOverrideOpen((o) => !o)} aria-expanded={overrideOpen}>Override verdict</Button>
                {human && !accepted && (
                  <Button variant="ghost" disabled={busy} onClick={() => act(() => override("cleared", "Override removed"), "Override removed")}>Remove override</Button>
                )}
                <Button onClick={reverify} disabled={busy || !canVerify} title={!canVerify ? "Available when the run has completed" : undefined}>
                  {run?.active ? (
                    <span className="h-3 w-3 rounded-full border-[1.5px] border-accent" style={{ borderRightColor: "transparent", animation: "tlSpin 800ms linear infinite" }} />
                  ) : null}
                  {run?.active ? "Verifying…" : "Re-run verification"}
                </Button>
              </div>
              {overrideOpen && (
                <form className="tl-in flex flex-col gap-2 rounded-md border border-border bg-subtle p-3" style={{ animationDuration: "180ms" }}
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (ovNote.trim().length < 5) return;
                    if (await act(() => override(ovVerdict, ovNote.trim()), `Verdict set to ${VERDICTS[ovVerdict as keyof typeof VERDICTS].label}`)) {
                      setOverrideOpen(false);
                      setOvNote("");
                    }
                  }}>
                  <label className="flex flex-col gap-1 text-xs font-medium text-fg2">
                    New verdict
                    <select value={ovVerdict} onChange={(e) => setOvVerdict(e.target.value)}
                      className="h-8 rounded-md border border-border-strong bg-panel px-2 text-[13px] text-fg">
                      {VERDICT_ORDER.map((v) => <option key={v} value={v}>{VERDICTS[v].label}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs font-medium text-fg2">
                    <span>Comment <span className="font-normal text-fg3">required, saved to the history</span></span>
                    <textarea value={ovNote} onChange={(e) => setOvNote(e.target.value)} rows={3} placeholder="What did you check, and why do you disagree?"
                      className="resize-y rounded-md border border-border-strong bg-panel p-2 font-sans text-[13px] leading-normal text-fg outline-none focus:border-accent" />
                  </label>
                  <div className="flex justify-end gap-2">
                    <Button onClick={() => setOverrideOpen(false)}>Cancel</Button>
                    <Button type="submit" variant="primary" disabled={busy || ovNote.trim().length < 5}>Save override</Button>
                  </div>
                </form>
              )}
            </div>
          </Section>

          <Section id="hist-h" title="History">
            <ol className="m-0 flex list-none flex-col px-4 pt-2 pb-3">
              {d.history.length === 0 && <li className="py-1.5 text-[13px] text-fg3">No history yet.</li>}
              {d.history.map((h, i) => {
                const m = verdictMeta(h.status);
                return (
                  <li key={i} className="tl-in grid gap-2.5 py-1.5" style={{ gridTemplateColumns: "12px minmax(0,1fr)" }}>
                    <span className="mt-1.5 h-2 w-2 rounded-full" style={{ background: h.status === "cleared" ? "var(--fg3)" : m.c }} />
                    <div className="text-[13px]">
                      <div>
                        <span className="font-medium">{h.kind === "override" ? "Reviewer" : "Verifier agent"}</span>{" "}
                        <span className="text-fg2">
                          {h.kind === "override"
                            ? h.status === "cleared" ? "removed the override" : `set the verdict to ${m.label}`
                            : `${m.label}${h.claims?.total ? ` · ${h.claims.supported} / ${h.claims.total} claims` : ""}${h.model ? ` · ${h.model}` : ""}`}
                        </span>
                      </div>
                      {h.note && <div className="text-xs text-fg2">“{h.note}”</div>}
                      <div className="font-mono text-[11px] text-fg3">{dateTime(h.at)}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </Section>
        </div>

        {/* Right column */}
        <div className="flex min-w-0 flex-col gap-4">
          <section ref={codePanel} aria-labelledby="code-h" className="min-w-0 rounded-lg border border-border bg-panel">
            <div className="flex items-center justify-between gap-3 px-4 pt-3">
              <h2 id="code-h" className="m-0 text-sm font-semibold">Code evidence</h2>
              {current && <Link to={`/runs/${id}/code?component=${encodeURIComponent(current.component_id)}`} className="text-xs">Open in code view →</Link>}
            </div>
            {d.components.length === 0 ? (
              <div className="px-4 py-4 text-[13px] text-fg3">No code was mapped to this requirement.</div>
            ) : (
              <>
                <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-border px-4 pt-2.5">
                  {d.components.map((c) => {
                    const on = c.component_id === current?.component_id;
                    const dir = c.role === "direct";
                    return (
                      <button key={c.component_id} role="tab" aria-selected={on} onClick={() => { setComp(c.component_id); setActiveClaim(null); }}
                        className="flex cursor-pointer flex-col items-start gap-0.5 border-0 bg-transparent px-2.5 pt-1.5 pb-2 whitespace-nowrap"
                        style={{ borderBottom: `2px solid ${on ? "var(--fg)" : "transparent"}` }}>
                        <span className="flex items-center gap-1.5">
                          <span className="rounded-[3px] px-[5px] font-mono text-[10px] leading-4 font-semibold tracking-[.04em]"
                            style={{ background: dir ? "var(--fg)" : "var(--hover)", color: dir ? "var(--bg)" : "var(--fg2)" }}>
                            {dir ? "DIRECT" : "SUPPORTING"}
                          </span>
                          <span className="font-mono text-[13px] font-medium" style={{ color: on ? "var(--fg)" : "var(--fg2)" }}>{c.name}</span>
                        </span>
                        <span className="font-mono text-[11px] text-fg3">{c.path.split("/").pop()} {c.start_line}–{c.end_line}</span>
                      </button>
                    );
                  })}
                </div>
                {current && (
                  <>
                    {current.docstring && (
                      <div className="px-4 pt-3">
                        <div className="rounded-md border border-dashed border-border-strong bg-subtle px-3 py-2.5">
                          <div className="mb-1 font-mono text-[11px] font-medium text-fg3">
                            {current.docstring.kind === "generated" ? "GENERATED DOCUMENTATION, NOT EVIDENCE" : "EXISTING DOCSTRING, NOT EVIDENCE"}
                          </div>
                          <div className="max-h-[120px] overflow-y-auto text-[13px] text-pretty whitespace-pre-line text-fg2">{current.docstring.content.trim()}</div>
                        </div>
                      </div>
                    )}
                    <div className="flex justify-between px-4 pt-3 pb-1.5 font-mono text-xs text-fg3">
                      <span>{current.path}</span><span>lines {current.start_line}–{current.end_line}</span>
                    </div>
                    <div ref={codeBox} className="mx-4 mb-4 max-h-[420px] overflow-auto rounded-md border border-border bg-code-bg" style={{ scrollBehavior: "smooth" }}>
                      <div role="presentation" className="min-w-max py-2">
                        {current.code.length === 0 && <div className="px-3 text-xs text-fg3">The source file is not available.</div>}
                        {current.code.map((ln) => {
                          const mk = marks[ln.n];
                          const pulsing = pulse && ln.n >= pulse.a && ln.n <= pulse.b;
                          return (
                            <div key={ln.n} data-line={ln.n} className="grid h-[22px] items-center"
                              style={{ gridTemplateColumns: "36px 44px auto", background: mk ? mk.meta.b : "transparent",
                                animation: pulsing ? `${pulse!.flip ? "tlPulseA" : "tlPulseB"} 700ms ease-out 1` : "none" }}>
                              <span className="flex h-full items-center justify-center" style={{ borderLeft: `3px solid ${mk ? mk.meta.c : "transparent"}` }}>
                                {mk?.mark && (
                                  <button onClick={() => setActiveClaim(mk.claim)} aria-label={`Go to claim ${mk.mark}`}
                                    className="h-4 cursor-pointer rounded-[3px] border-0 px-1 font-mono text-[10px] leading-4 font-semibold"
                                    style={{ background: mk.meta.c, color: "var(--panel)" }}>
                                    {mk.mark}
                                  </button>
                                )}
                              </span>
                              <span className="pr-4 text-right font-mono text-xs text-fg3 select-none">{ln.n}</span>
                              <code className="pr-6 font-mono text-[13px] leading-[22px] whitespace-pre text-fg">{ln.text || " "}</code>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
          </section>

          {graph && d.components.length > 0 && (
            <section aria-labelledby="graph-h" className="rounded-lg border border-border bg-panel">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <h2 id="graph-h" className="m-0 text-sm font-semibold">Mapping subgraph</h2>
                <div className="flex gap-4 text-xs text-fg3"><span>Requirement</span><span>→ Direct</span><span>→ Supporting</span></div>
              </div>
              <div ref={graphBox} className="overflow-x-auto p-4">
                <div className="relative" style={{ width: graph.width, height: graph.height, minWidth: GRAPH_MIN_W }}>
                  <svg width={graph.width} height={graph.height} className="absolute inset-0 overflow-visible" aria-hidden="true">
                    {graph.edges.map((e, i) => {
                      const on = !hover || e.from === hover || e.to === hover;
                      const maps = e.label === "maps to";
                      return (
                        <path key={i} d={e.d} fill="none" stroke={maps ? "var(--accent)" : "var(--border-strong)"}
                          strokeWidth={on && hover ? 2 : 1.25} strokeDasharray={maps ? "4 3" : undefined}
                          style={{ opacity: on ? 1 : 0.2, transition: "opacity 150ms ease-out" }} />
                      );
                    })}
                  </svg>
                  {graph.edges.filter((e) => e.label !== "maps to").map((e, i) => (
                    <span key={i} className="absolute bg-panel px-1 font-mono text-[11px] whitespace-nowrap text-fg3"
                      style={{ left: e.lx, top: e.ly, transform: "translate(-50%,-50%)", opacity: !hover || e.from === hover || e.to === hover ? 1 : 0.2, transition: "opacity 150ms ease-out" }}>
                      {e.label}
                    </span>
                  ))}
                  {graph.nodes.map((n) => {
                    const touched = !hover || hover === n.key || graph.edges.some((e) => (e.from === hover && e.to === n.key) || (e.to === hover && e.from === n.key));
                    const req = n.key === "req";
                    const selected = n.key === current?.component_id;
                    return (
                      <button key={n.key}
                        onClick={() => { if (!req) { setComp(n.key); setActiveClaim(null); codePanel.current?.scrollIntoView({ behavior: "smooth", block: "start" }); } }}
                        onMouseEnter={() => setHover(n.key)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.key)} onBlur={() => setHover(null)}
                        className="absolute flex h-10 cursor-pointer flex-col justify-center rounded-md border px-2.5 text-left transition-[opacity,border-color] duration-150"
                        style={{ left: n.x, top: n.y, width: n.w, opacity: touched ? 1 : 0.35,
                          borderColor: req ? "var(--accent)" : selected ? "var(--fg)" : "var(--border-strong)",
                          background: req ? "var(--accent-bg)" : selected ? "var(--subtle)" : "var(--panel)",
                          boxShadow: hover === n.key ? "0 0 0 3px var(--hover)" : "none" }}>
                        <span className="font-mono text-[9px] leading-[1.2] font-semibold tracking-[.05em]"
                          style={{ color: req ? "var(--accent)" : n.kind === "DIRECT" ? "var(--fg2)" : "var(--fg3)" }}>{n.kind}</span>
                        <span className="truncate font-mono text-xs leading-[1.3] font-medium text-fg">{n.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>
          )}

          <section className="rounded-lg border border-border bg-panel">
            <button onClick={() => setWhyOpen((o) => !o)} aria-expanded={whyOpen}
              className="flex w-full cursor-pointer items-center gap-2.5 border-0 bg-transparent px-4 py-3 text-left">
              <span className="inline-block text-[10px] text-fg3 transition-transform duration-150 ease-out" style={{ transform: whyOpen ? "rotate(90deg)" : "none" }}>▶</span>
              <span className="text-sm font-semibold">Why these code locations</span>
              <span className="text-xs text-fg3">Search ranks and selection method</span>
            </button>
            {whyOpen && (
              <div className="tl-in overflow-x-auto border-t border-border" style={{ animationDuration: "180ms" }}>
                <div className="min-w-[720px]">
                  <div className="grid h-8 items-center gap-3 border-b border-border px-4 text-xs font-medium text-fg3"
                    style={{ gridTemplateColumns: "minmax(180px,1.2fr) 100px 60px 80px 80px minmax(160px,1.4fr)" }}>
                    <span>Component</span><span>Role</span><span>Rank</span><span>Keyword</span><span>Semantic</span><span>Selected because</span>
                  </div>
                  {why.map((w) => (
                    <div key={w.name + w.role} className="grid min-h-9 items-center gap-3 border-b border-border px-4 text-[13px] last:border-b-0"
                      style={{ gridTemplateColumns: "minmax(180px,1.2fr) 100px 60px 80px 80px minmax(160px,1.4fr)", color: w.role === "Not selected" ? "var(--fg3)" : undefined }}>
                      <span className="truncate font-mono text-xs">{w.name}</span>
                      <span className="text-xs text-fg2">{w.role}</span>
                      <span className="font-mono text-xs">{w.rank}</span>
                      <span className="font-mono text-xs text-fg2">{w.keyword}</span>
                      <span className="font-mono text-xs text-fg2">{w.semantic}</span>
                      <span className="text-xs text-fg2">{w.because}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      </div>

      {toast && (
        <div role="status" className="tl-in fixed right-6 bottom-6 z-[6] rounded-lg bg-fg px-4 py-2.5 text-[13px] text-bg shadow-panel">{toast}</div>
      )}
    </div>
  );
}
