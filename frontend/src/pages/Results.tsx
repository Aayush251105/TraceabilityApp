import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useResults, useRun } from "../api/hooks";
import type { ResultRow } from "../api/types";
import { Button } from "../components/ui/Button";
import { Alert, Segmented } from "../components/ui/Form";
import { XIcon } from "../components/ui/Icon";
import { Glyph, StatusChip } from "../components/ui/Status";
import { approx, clock, dateTime, plural } from "../lib/format";
import { filterRows, sortRows, supportedByType, typeLabel, verdictCounts, type SortKey, type TypeFilter } from "../lib/results";
import { commitLabel, repoLabel } from "../lib/runs";
import { VERDICT_ORDER, VERDICTS, verdictMeta, type Verdict } from "../lib/status";

const COLS = "28px 80px minmax(160px,1fr) 104px 210px 64px 60px minmax(110px,160px) 80px";
const FLAG_COLOUR = { info: "var(--fg3)", warn: "var(--part)", error: "var(--bad)" } as const;

/** 0 → 1 over 900 ms (ease-out), immediately 1 with reduced motion. */
function useReveal(ready: boolean) {
  const [p, setP] = useState(0);
  useEffect(() => {
    if (!ready) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setP(1);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const x = Math.min(1, (now - t0) / 900);
      setP(1 - Math.pow(1 - x, 3));
      if (x < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [ready]);
  return p;
}

function ExportMenu({ runId, rows }: { runId: number; rows: number }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);
  const item = "flex w-full items-center justify-between rounded-[5px] px-2.5 py-2 text-left text-[13px] text-fg no-underline hover:bg-hover hover:no-underline";
  return (
    <div ref={box} className="relative">
      <Button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu">
        Export <span className="text-[9px] text-fg3">▼</span>
      </Button>
      {open && (
        <div role="menu" className="tl-in absolute top-[38px] right-0 z-[5] w-[250px] rounded-lg border border-border-strong bg-panel p-1 shadow-panel"
          style={{ animationDuration: "150ms" }}>
          <button role="menuitem" className={`${item} cursor-pointer border-0 bg-transparent`} onClick={() => { setOpen(false); window.print(); }}>
            <span>PDF report</span><span className="font-mono text-[11px] text-fg3">print · save as PDF</span>
          </button>
          <a role="menuitem" className={item} href={`/api/runs/${runId}/export.csv`} download onClick={() => setOpen(false)}>
            <span>CSV</span><span className="font-mono text-[11px] text-fg3">{plural(rows, "row")}</span>
          </a>
          <a role="menuitem" className={item} href={`/api/runs/${runId}/export.json`} download onClick={() => setOpen(false)}>
            <span>JSON</span><span className="font-mono text-[11px] text-fg3">full, with citations</span>
          </a>
        </div>
      )}
    </div>
  );
}

function Loading() {
  return (
    <div className="flex flex-col gap-4 px-8 py-6" aria-busy="true" aria-label="Loading results">
      <div className="tl-skeleton h-[132px] rounded-lg" />
      <div className="grid grid-cols-6 gap-2">{Array.from({ length: 6 }, (_, i) => <div key={i} className="h-[72px] rounded-lg bg-subtle" />)}</div>
      <div className="h-[360px] rounded-lg bg-subtle" />
    </div>
  );
}

export function Results() {
  const { runId } = useParams();
  const id = Number(runId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: run } = useRun(id);
  const { data, isLoading, error } = useResults(id, { live: !!run?.active });
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [type, setType] = useState<TypeFilter>("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("id");
  const [dir, setDir] = useState<1 | -1>(1);
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [toast, setToast] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const p = useReveal(!!data?.ready);

  // Re-verification runs in the background: refresh the run while it is active.
  useEffect(() => {
    if (!run?.active) return;
    const iv = setInterval(() => qc.invalidateQueries({ queryKey: keys.run(id) }), 3000);
    return () => clearInterval(iv);
  }, [run?.active, id, qc]);

  if (isLoading) return <><ResultsHeader id={id} run={run} rows={0} /><Loading /></>;
  if (error || !data) {
    return <div className="px-8 py-6"><Alert tone="error" title="Could not load results.">{(error as ApiError)?.message}</Alert></div>;
  }
  if (!data.ready) {
    return (
      <>
        <ResultsHeader id={id} run={run} rows={0} />
        <div className="px-8 py-6">
          <Alert tone="info">
            Results appear once requirements are indexed and verified. <Link to={`/runs/${id}/pipeline`}>Watch the pipeline →</Link>
          </Alert>
        </div>
      </>
    );
  }

  const rows = data.requirements;
  const summary = data.summary!;
  const counts = verdictCounts(rows);
  const total = rows.length;
  const types = supportedByType(rows);
  const visible = sortRows(filterRows(rows, { verdict, type, q }), sort, dir);
  const selected = Object.keys(sel).filter((k) => sel[k]);
  const allSel = visible.length > 0 && visible.every((r) => sel[r.requirement_id]);
  const notSupported = counts.not_supported_by_candidate;
  const notFound = counts.not_found;
  const lni = notSupported + notFound;
  const comps = summary.components;
  const uncited = comps.total - comps.cited_as_evidence;
  const incomplete = run?.status !== "completed";

  const rerun = async () => {
    setActionError(null);
    try {
      await api.json("POST", `/api/runs/${id}/verify`, { requirement_ids: selected });
      setToast(`Re-verifying ${plural(selected.length, "requirement")} · ${approx(selected.length * 20)}`);
      setSel({});
      setTimeout(() => setToast(null), 6000);
      await qc.invalidateQueries({ queryKey: keys.run(id) });
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  };

  const header = (key: SortKey | null, label: string, align: "left" | "right" = "left") => (
    <button key={label} onClick={() => key && (sort === key ? setDir((d) => (d === 1 ? -1 : 1)) : (setSort(key), setDir(1)))}
      aria-sort={key && sort === key ? (dir === 1 ? "ascending" : "descending") : "none"}
      className={`flex cursor-pointer gap-1 border-0 bg-transparent p-0 text-xs font-medium ${align === "right" ? "justify-end" : ""}`}
      style={{ color: key && sort === key ? "var(--fg)" : "var(--fg3)", cursor: key ? "pointer" : "default" }}>
      {label}<span className="text-[9px]">{key && sort === key ? (dir === 1 ? "▲" : "▼") : ""}</span>
    </button>
  );

  return (
    <div className="flex flex-col">
      <ResultsHeader id={id} run={run} rows={total} />
      <div className="flex max-w-[1440px] flex-col gap-4 px-8 pt-6 pb-12">
        {incomplete && run && (
          <Alert tone="warn" title={run.status === "running" ? "Verification is still running." : "Partial results."}>
            {run.status === "running" ? "Verdicts appear as each requirement finishes." : "The run stopped before every requirement was verified."}{" "}
            <Link to={`/runs/${id}/pipeline`}>Open the pipeline →</Link>
          </Alert>
        )}
        {actionError && <Alert tone="error">{actionError}</Alert>}

        {/* Summary */}
        <section aria-label="Summary" className="grid rounded-lg border border-border bg-panel" style={{ gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)" }}>
          <div className="flex flex-col gap-4 border-r border-border px-6 py-5">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="font-mono text-[40px] leading-none font-medium tracking-[-0.03em]">{Math.round(counts.supported * p)}</span>
              <span className="text-xl text-fg2">of <span className="font-mono">{total}</span> requirements supported</span>
            </div>
            <div role="img" aria-label={VERDICT_ORDER.map((v) => `${counts[v]} ${VERDICTS[v].label}`).join(", ")}
              className="flex h-3 gap-0.5 overflow-hidden rounded-[3px] bg-panel">
              {VERDICT_ORDER.map((v) => (
                <span key={v} title={`${VERDICTS[v].label}: ${counts[v]}`}
                  style={{ flex: Math.max(0.0001, counts[v] * p), background: VERDICTS[v].c, opacity: !verdict || verdict === v ? 1 : 0.25,
                    transition: "opacity 150ms ease-out" }} />
              ))}
            </div>
            <div className="flex flex-wrap gap-4 text-xs text-fg2">
              {VERDICT_ORDER.map((v) => (
                <span key={v} className="inline-flex items-center gap-1.5">
                  <Glyph meta={VERDICTS[v]} />{VERDICTS[v].label} <span className="font-mono text-fg3">{counts[v]}</span>
                </span>
              ))}
              {summary.pending > 0 && <span className="text-fg3">{summary.pending} not verified yet</span>}
            </div>
          </div>
          <div className="grid" style={{ gridTemplateRows: "1fr 1fr" }}>
            <div className="border-b border-border px-6 py-4">
              <div className="text-xs text-fg3">Likely not implemented</div>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-2xl leading-[1.3] font-medium text-bad">{Math.round(lni * p)}</span>
                <span className="text-[13px] text-fg2">{notSupported} not supported by candidate + {notFound} not found</span>
              </div>
              <div className="text-xs text-pretty text-fg3">Not found means the search found no candidate code. That does not prove the feature is absent.</div>
            </div>
            <div className="grid grid-cols-2">
              <div className="border-r border-border px-6 py-4">
                <div className="text-xs text-fg3">By type</div>
                <div className="mt-0.5 text-[13px]">Functional <span className="font-mono">{types.functional.supported} / {types.functional.total}</span></div>
                <div className="text-[13px]">Non-functional <span className="font-mono">{types.nonFunctional.supported} / {types.nonFunctional.total}</span></div>
              </div>
              <Link to={`/runs/${id}/code`} className="px-6 py-4 text-fg no-underline hover:bg-subtle hover:no-underline">
                <div className="text-xs text-fg3">Code coverage</div>
                <div className="mt-0.5 text-[13px]"><span className="font-mono">{Math.round(comps.cited_as_evidence * p)}</span> of {comps.total} components cited as evidence</div>
                <div className="text-[13px] text-accent">{uncited} without evidence →</div>
              </Link>
            </div>
          </div>
        </section>

        {/* Verdict cards (filters) */}
        <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
          {VERDICT_ORDER.map((v) => {
            const m = VERDICTS[v];
            const on = verdict === v;
            return (
              <button key={v} onClick={() => setVerdict(on ? null : v)} aria-pressed={on}
                className="flex cursor-pointer flex-col gap-1.5 rounded-lg border bg-panel px-3.5 py-3 text-left transition-[border-color] duration-150 hover:border-border-strong"
                style={{ borderColor: on ? m.c : "var(--border)", boxShadow: on ? `0 0 0 3px ${m.b}` : "none" }}>
                <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: m.c }}><Glyph meta={m} />{m.label}</span>
                <span className="font-mono text-2xl leading-none font-medium text-fg">{Math.round(counts[v] * p)}</span>
              </button>
            );
          })}
        </div>

        {/* Requirements table */}
        <section aria-label="Requirements" className="rounded-lg border border-border bg-panel">
          <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2.5">
            <label className="flex h-[30px] max-w-[340px] min-w-[220px] flex-1 items-center gap-2 rounded-md border border-border-strong px-2.5">
              <span aria-hidden="true" className="h-2.5 w-2.5 flex-none rounded-full border-[1.5px] border-fg3" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by ID or title" aria-label="Search requirements"
                className="flex-1 border-0 bg-transparent text-[13px] text-fg outline-none placeholder:text-fg3" />
            </label>
            <Segmented label="Requirement type" value={type} onChange={setType}
              options={[{ id: "all", label: "All" }, { id: "fr", label: "Functional" }, { id: "nfr", label: "Non-functional" }]} />
            {verdict && (
              <span className="inline-flex h-[26px] items-center gap-1.5 rounded bg-accent-bg pr-1.5 pl-2.5 text-xs font-medium text-accent">
                Verdict: {VERDICTS[verdict].label}
                <button onClick={() => setVerdict(null)} aria-label="Clear verdict filter" className="flex cursor-pointer border-0 bg-transparent text-accent"><XIcon /></button>
              </span>
            )}
            <span className="ml-auto text-xs text-fg3">{visible.length} of {total} shown</span>
            <Button variant={selected.length ? "primary" : "secondary"} disabled={!selected.length || !!run?.active || run?.status !== "completed"} onClick={rerun}
              title={run?.status !== "completed" ? "Available when the run has completed" : undefined}>
              {selected.length ? `Re-run verification (${selected.length})` : "Re-run verification"}
            </Button>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[980px]">
              <div className="grid h-9 items-center gap-2.5 border-b border-border px-3" style={{ gridTemplateColumns: COLS }}>
                <input type="checkbox" checked={allSel} aria-label="Select all"
                  onChange={() => setSel((s) => ({ ...s, ...Object.fromEntries(visible.map((r) => [r.requirement_id, !allSel])) }))}
                  className="m-0 h-[15px] w-[15px] accent-[var(--accent)]" />
                {header("id", "ID")}{header("title", "Title")}{header("type", "Type")}{header("verdict", "Verdict")}
                {header("claims", "Claims")}{header("links", "Linked")}{header(null, "Flags")}{header(null, "Human", "right")}
              </div>
              {visible.map((r: ResultRow) => {
                const href = `/runs/${id}/requirements/${encodeURIComponent(r.requirement_id)}`;
                const flag = r.flags[0];
                return (
                  <div key={r.requirement_id} onClick={() => navigate(href)}
                    className="grid min-h-11 cursor-pointer items-center gap-2.5 border-b border-border px-3 text-[13px] last:border-b-0 hover:bg-subtle"
                    style={{ gridTemplateColumns: COLS, background: sel[r.requirement_id] ? "var(--accent-bg)" : undefined }}>
                    <input type="checkbox" checked={!!sel[r.requirement_id]} aria-label={`Select ${r.requirement_id}`}
                      onClick={(e) => e.stopPropagation()} onChange={() => setSel((s) => ({ ...s, [r.requirement_id]: !s[r.requirement_id] }))}
                      className="m-0 h-[15px] w-[15px] accent-[var(--accent)]" />
                    <Link to={href} onClick={(e) => e.stopPropagation()} className="font-mono text-xs font-medium text-fg">{r.requirement_id}</Link>
                    <span className="truncate">{r.title}</span>
                    <span className="text-xs text-fg2">{typeLabel(r.type)}</span>
                    <span><StatusChip meta={verdictMeta(r.verdict.status)} /></span>
                    <span className="font-mono text-xs text-fg2">{r.claims.total ? `${r.claims.supported} / ${r.claims.total}` : "—"}</span>
                    <span className="font-mono text-xs text-fg2">{r.links.total}</span>
                    <span className="truncate text-xs" title={r.flags.map((f) => f.label).join("; ") || undefined}
                      style={{ color: flag ? FLAG_COLOUR[flag.level] : "var(--fg3)" }}>
                      {flag ? flag.label : "—"}{r.flags.length > 1 ? ` +${r.flags.length - 1}` : ""}
                    </span>
                    <span className="text-right text-xs text-fg3">{r.human ?? "—"}</span>
                  </div>
                );
              })}
              {visible.length === 0 && (
                <div className="px-4 py-10 text-center text-[13px] text-fg3">
                  No requirements match these filters.{" "}
                  <button onClick={() => { setVerdict(null); setType("all"); setQ(""); }} className="cursor-pointer border-0 bg-transparent p-0 text-accent">Reset filters</button>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      {toast && (
        <div role="status" className="tl-in fixed right-6 bottom-6 z-[5] rounded-lg bg-fg px-4 py-2.5 text-[13px] text-bg shadow-panel">
          {toast} <Link to={`/runs/${id}/pipeline`} className="ml-2 text-bg underline">View progress</Link>
        </div>
      )}
    </div>
  );
}

function ResultsHeader({ id, run, rows }: { id: number; run: ReturnType<typeof useRun>["data"]; rows: number }) {
  const duration = run?.started_at && run.finished_at ? (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000 : null;
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border bg-panel px-8 pt-5 pb-4">
      <div className="min-w-0">
        <div className="mb-0.5 text-xs text-fg3">
          <Link to="/" className="text-fg3">Runs</Link> / <Link to={`/runs/${id}/pipeline`} className="text-fg3">Run #{id}</Link> / Results
        </div>
        <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">{run?.name ?? `Run #${id}`}</h1>
        {run && (
          <div className="mt-0.5 font-mono text-xs text-fg3">
            {run.srs_filename} · {repoLabel(run)} @ {commitLabel(run)}
            {run.finished_at && ` · ${run.status === "completed" ? "completed" : run.status} ${dateTime(run.finished_at)} · ${clock(duration)}`}
            {run.models?.verifier && ` · verified with ${run.models.verifier}`}
          </div>
        )}
      </div>
      <div className="flex gap-2 print:hidden">
        <Link to={`/runs/${id}/code`}
          className="inline-flex h-8 items-center rounded-md border border-border-strong bg-panel px-3 text-[13px] font-medium text-fg no-underline hover:bg-hover hover:no-underline">
          Code view
        </Link>
        <ExportMenu runId={id} rows={rows} />
      </div>
    </header>
  );
}
