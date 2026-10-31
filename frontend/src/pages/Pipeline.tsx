import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useResults, useRun, useRunStream } from "../api/hooks";
import type { ResultRow, RunDetail, RunEvent } from "../api/types";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/Dialog";
import { Alert } from "../components/ui/Form";
import { ProgressBar } from "../components/ui/Progress";
import { StatusChip } from "../components/ui/Status";
import { approx, clock, percent, plural, timeOfDay } from "../lib/format";
import {
  agentCards, codeLane, ingestDone, overallColor, overallLabel, railSub, runElapsed, srsLane, stageMap,
  traceStarted, type AgentCard, type LaneView, type StepRow,
} from "../lib/pipeline";
import { commitLabel, repoLabel } from "../lib/runs";
import { stageMeta, verdictMeta } from "../lib/status";

function useTick(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [active]);
  return now;
}

/** Glyph for a step / rail item (sizes from the design). */
function StepGlyph({ state, size = 14 }: { state: string; size?: number }) {
  const m = stageMeta(state);
  return (
    <span
      aria-hidden="true"
      className="inline-block flex-none text-center"
      style={{
        width: size, height: size, borderRadius: m.r, border: `1.5px solid ${m.c}`, background: m.ib,
        color: "var(--panel)", font: `700 ${Math.round(size * 0.56)}px/${size - 3}px 'IBM Plex Mono',monospace`,
      }}
    >
      {m.g}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Header: title, timers, cancel, overall bar, stage rail
// ---------------------------------------------------------------------------

function Header({ run, now, onCancel }: { run: RunDetail; now: number; onCancel: () => void }) {
  const paused = run.status === "paused";
  const failed = run.status === "failed" || run.status === "cancelled";
  const elapsed = runElapsed(run, now);
  const remaining = run.status === "completed" ? "0 min" : paused || failed ? "—" : approx(run.progress.remaining_seconds);
  const pct = run.status === "completed" ? 1 : run.progress.fraction;
  const color = overallColor(run.status);
  return (
    <header className="border-b border-border bg-panel">
      <div className="flex flex-wrap items-end justify-between gap-6 px-8 pt-5 pb-4">
        <div className="min-w-0">
          <div className="mb-0.5 text-xs text-fg3">
            <Link to="/" className="text-fg3">Runs</Link> / Run #{run.run_id}
          </div>
          <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">{run.name}</h1>
          <div className="mt-0.5 font-mono text-xs text-fg3">
            {run.srs_filename} · {repoLabel(run)} @ {commitLabel(run)}
          </div>
        </div>
        <div className="flex items-end gap-8">
          <div>
            <div className="flex items-center gap-1.5 text-xs">
              {paused && (
                <span aria-hidden="true" className="inline-flex gap-0.5">
                  <span className="h-2.5 w-[3px] bg-rev" />
                  <span className="h-2.5 w-[3px] bg-rev" />
                </span>
              )}
              <span style={{ color: paused ? "var(--rev)" : failed ? "var(--bad)" : "var(--fg3)" }}>
                {paused ? "Paused for review" : run.status === "failed" ? "Stopped" : run.status === "cancelled" ? "Cancelled" : "Elapsed"}
              </span>
            </div>
            <div aria-live="off" className="font-mono text-2xl leading-tight font-medium tracking-[-0.02em]"
              style={{ color: paused || failed ? "var(--fg3)" : "var(--fg)" }}>
              {clock(elapsed)}
            </div>
          </div>
          <div>
            <div className="text-xs text-fg3">Estimated remaining</div>
            <div className="font-mono text-2xl leading-tight font-medium tracking-[-0.02em] text-fg2">{remaining}</div>
          </div>
          {(run.status === "running" || paused || run.status === "queued") && (
            <Button onClick={onCancel} className="hover:border-bad hover:text-bad">Cancel run</Button>
          )}
        </div>
      </div>
      <div className="px-8 pb-4">
        <div className="mb-1.5 flex justify-between text-xs text-fg3">
          <span>{overallLabel(run)}</span>
          <span className="font-mono">{percent(pct)}</span>
        </div>
        <ProgressBar value={pct} color={color} label="Overall progress" />
      </div>
      <ol aria-label="Pipeline stages" className="m-0 grid list-none grid-cols-6 border-t border-border px-8 py-0">
        {run.rail.map((step) => {
          const m = stageMeta(step.status);
          const active = step.status === "running" || step.status === "waiting";
          return (
            <li key={step.group} aria-current={active ? "step" : undefined}
              className="flex min-w-0 items-center gap-2.5 py-3 pr-3"
              style={{ borderBottom: `2px solid ${step.status === "queued" ? "var(--border)" : m.c}` }}>
              <StepGlyph state={step.status} size={18} />
              <span className="flex min-w-0 flex-col">
                <span className="text-[13px] font-medium" style={{ color: step.status === "queued" ? "var(--fg3)" : "var(--fg)" }}>
                  {step.label}
                </span>
                <span className="truncate text-xs" style={{ color: step.status === "done" || step.status === "queued" ? "var(--fg3)" : m.c }}>
                  {railSub(step, run)}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Lanes
// ---------------------------------------------------------------------------

const LOG_COLOUR: Record<string, string> = { ok: "var(--ok)", warn: "var(--rev)", error: "var(--bad)", info: "var(--fg2)" };

function ActivityLog({ events }: { events: RunEvent[] }) {
  const box = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (!paused && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events, paused]);
  return (
    <div className="mt-auto border-t border-border">
      <div className="flex items-center justify-between px-4 py-2">
        <span className="text-xs font-medium text-fg3">Activity</span>
        <button onClick={() => setPaused((p) => !p)} aria-pressed={paused}
          className="h-6 cursor-pointer rounded border border-border bg-panel px-2 text-xs text-fg2 hover:bg-hover">
          {paused ? "Resume scroll" : "Pause scroll"}
        </button>
      </div>
      <div ref={box} role="log" aria-live="polite" className="h-[148px] overflow-y-auto px-4 pb-2.5 font-mono text-xs leading-5">
        {events.length === 0 && <div className="text-fg3">Nothing yet.</div>}
        {events.map((e) => (
          <div key={e.event_id} className="tl-in grid gap-2" style={{ gridTemplateColumns: "64px minmax(0,1fr)", animationDuration: "180ms" }}>
            <span className="text-fg3">{timeOfDay(e.ts)}</span>
            <span className="truncate" title={e.message} style={{ color: LOG_COLOUR[e.level] ?? "var(--fg2)" }}>{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Step({ step }: { step: StepRow }) {
  const running = step.state === "running";
  return (
    <li className="grid items-start gap-2.5 px-4 py-2" style={{ gridTemplateColumns: "16px minmax(0,1fr) auto", background: running ? "var(--accent-bg)" : "transparent" }}>
      <span className="mt-[3px]"><StepGlyph state={step.state} /></span>
      <span className="min-w-0">
        <span className="block text-[13px]" style={{ fontWeight: running ? 600 : 400, color: step.state === "queued" ? "var(--fg3)" : "var(--fg)" }}>
          {step.label}
        </span>
        {step.detail && <span className="block text-xs text-fg3">{step.detail}</span>}
        {step.agents && (
          <>
            <span className="mt-1.5 block text-xs text-fg2">
              Writing docstring for <code className="font-mono text-xs font-medium text-fg">{step.target}</code>
            </span>
            <span className="mt-1.5 flex flex-wrap gap-1">
              {step.agents.map((a) => (
                <span key={a.label}
                  className="inline-flex h-[22px] items-center gap-1 rounded border px-2 font-mono text-[11px] font-medium transition-colors duration-200"
                  style={{
                    borderColor: a.state === "current" ? "var(--accent)" : a.state === "done" ? "transparent" : "var(--border)",
                    background: a.state === "done" ? "var(--ok-bg)" : a.state === "current" ? "var(--panel)" : "transparent",
                    color: a.state === "done" ? "var(--ok)" : a.state === "current" ? "var(--accent)" : "var(--fg3)",
                  }}>
                  {a.label} <span>{a.state === "done" ? "✓" : a.state === "current" ? "…" : ""}</span>
                </span>
              ))}
            </span>
          </>
        )}
      </span>
      <span className="font-mono text-xs text-fg3">{step.time}</span>
    </li>
  );
}

function Lane({ lane, events }: { lane: LaneView; events: RunEvent[] }) {
  const m = stageMeta(lane.state);
  return (
    <section className="flex min-w-0 flex-col rounded-lg border border-border bg-panel">
      <div className="flex flex-col gap-2.5 border-b border-border px-4 py-3.5">
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="font-mono text-[11px] font-medium text-fg3">{lane.lane}</span>
            <h2 className="m-0 truncate text-sm font-semibold">{lane.title}</h2>
          </div>
          <div className="flex gap-4 font-mono text-xs whitespace-nowrap text-fg3">
            <span>Elapsed {clock(lane.elapsed)}</span>
            <span style={{ color: lane.state === "done" ? "var(--ok)" : undefined }}>
              {lane.state === "done" ? "Done" : lane.state === "failed" ? "Failed" : `ETA ${approx(lane.eta)}`}
            </span>
          </div>
        </div>
        <div className="flex justify-between text-[13px]">
          <span>{lane.counter}</span>
          <span className="font-mono text-fg3">{percent(lane.fraction)}</span>
        </div>
        <ProgressBar value={lane.fraction} height={4} color={lane.state === "done" ? "var(--ok)" : lane.state === "failed" ? "var(--bad)" : "var(--accent)"} label={`${lane.title} progress`} />
      </div>
      <ol className="m-0 flex list-none flex-col py-2 pl-0">
        {lane.steps.map((s) => <Step key={s.key} step={s} />)}
      </ol>
      <ActivityLog events={events} />
      <span className="sr-only">{m.label}</span>
    </section>
  );
}

function LaneSummary({ lane, text }: { lane: LaneView; text: React.ReactNode }) {
  const m = stageMeta(lane.state);
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border bg-panel p-4">
      <div className="flex justify-between">
        <h2 className="m-0 text-sm font-semibold">{lane.lane} · {lane.title.split(" · ")[0]}</h2>
        <span className="flex items-center gap-1.5 text-xs" style={{ color: m.c }}>
          <StepGlyph state={lane.state} size={12} />
          {lane.state === "done" ? `Done in ${clock(lane.elapsed)}` : m.label}
        </span>
      </div>
      <div className="text-[13px] text-fg2">{text}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Tracing
// ---------------------------------------------------------------------------

function Agent({ card }: { card: AgentCard }) {
  const m = stageMeta(card.state);
  return (
    <section className="flex flex-col gap-2 rounded-lg border bg-panel px-4 py-3.5" style={{ borderColor: card.state === "failed" ? "var(--bad)" : "var(--border)" }}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold">{card.name}</h2>
        <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: m.c }}>
          <StepGlyph state={card.state} size={12} />
          {card.state === "running" ? "Running" : m.label}
        </span>
      </div>
      <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-[13px]">
        <span className="font-mono whitespace-nowrap">{card.counter}</span>
        <span className="font-mono text-xs text-fg3">{card.time}</span>
      </div>
      <ProgressBar value={card.fraction} height={4} color={m.c} label={`${card.name} progress`} />
      <div className="text-xs text-fg3">{card.note}</div>
    </section>
  );
}

const STREAM_COLS = "88px minmax(0,1fr) 230px 72px 88px 64px";

function VerifiedStream({ run, rows }: { run: RunDetail; rows: ResultRow[] }) {
  const s = stageMap(run);
  const verify = s.verify;
  const current = verify?.status === "running" ? verify.detail?.current : null;
  const done = rows.filter((r) => r.verified_at && r.verdict.status !== "pending")
    .sort((a, b) => Date.parse(a.verified_at!) - Date.parse(b.verified_at!));
  const start = verify?.started_at ? Date.parse(verify.started_at) : null;
  const timed = done.map((r, i) => {
    const prev = i === 0 ? start : Date.parse(done[i - 1].verified_at!);
    return { r, seconds: prev != null ? (Date.parse(r.verified_at!) - prev) / 1000 : null };
  }).reverse();
  const currentRow = current ? rows.find((r) => r.requirement_id === current) : null;
  return (
    <section className="rounded-lg border border-border bg-panel">
      <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-3">
        <h2 className="m-0 text-sm font-semibold">Verified so far</h2>
        <span className="text-xs text-fg3">Results appear as each requirement finishes. Verdicts can change after human review.</span>
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[820px]">
          <div className="grid h-8 items-center gap-4 border-b border-border px-4 text-xs font-medium text-fg3" style={{ gridTemplateColumns: STREAM_COLS }}>
            <span>ID</span><span>Title</span><span>Verdict</span><span>Claims</span><span>Components</span><span className="text-right">Time</span>
          </div>
          {current && (
            <div className="grid h-11 items-center gap-4 border-b border-border bg-accent-bg px-4 text-[13px]" style={{ gridTemplateColumns: STREAM_COLS }}>
              <span className="font-mono text-xs font-medium">{current}</span>
              <span className="truncate">{currentRow?.title ?? ""}</span>
              <span className="flex items-center gap-2 text-xs text-accent">
                <span className="h-3 w-3 rounded-full border-[1.5px] border-accent" style={{ borderRightColor: "transparent", animation: "tlSpin 1s linear infinite" }} />
                Verifying claims…
              </span>
              <span className="font-mono text-xs text-fg3">—</span>
              <span className="font-mono text-xs text-fg3">{currentRow?.links.total ?? "—"}</span>
              <span className="text-right font-mono text-xs text-fg3" />
            </div>
          )}
          <div className="max-h-[440px] overflow-y-auto">
            {timed.length === 0 && !current && <div className="px-4 py-6 text-center text-[13px] text-fg3">No requirement has been verified yet.</div>}
            {timed.map(({ r, seconds }) => (
              <Link key={r.requirement_id} to={`/runs/${run.run_id}/requirements/${encodeURIComponent(r.requirement_id)}`}
                className="tl-in grid min-h-11 items-center gap-4 border-b border-border px-4 text-[13px] text-fg no-underline last:border-b-0 hover:bg-subtle hover:no-underline"
                style={{ gridTemplateColumns: STREAM_COLS }}>
                <span className="font-mono text-xs font-medium">{r.requirement_id}</span>
                <span className="truncate">{r.title}</span>
                <span><StatusChip meta={verdictMeta(r.verdict.status)} /></span>
                <span className="font-mono text-xs text-fg2">{r.claims.total ? `${r.claims.supported}/${r.claims.total}` : "—"}</span>
                <span className="font-mono text-xs text-fg2">{r.links.total}</span>
                <span className="text-right font-mono text-xs text-fg3">{clock(seconds)}</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function FailurePanel({ run, verified, onResume, resuming }: { run: RunDetail; verified: number; onResume: () => void; resuming: boolean }) {
  const failed = (run.stages ?? []).find((s) => s.status === "failed" || s.status === "cancelled");
  const errors = (run.stages ?? []).filter((s) => s.status === "failed" && s.error);
  const cancelled = run.status === "cancelled";
  const title = cancelled ? "Run cancelled" : failed ? `${failed.label} stopped` : "The run could not start";
  const verify = stageMap(run).verify;
  return (
    <section role="alert" className="tl-in overflow-hidden rounded-lg border bg-panel" style={{ borderColor: cancelled ? "var(--border-strong)" : "var(--bad)" }}>
      <div className="flex flex-wrap items-start gap-3 px-5 py-4" style={{ background: cancelled ? "var(--nf-bg)" : "var(--bad-bg)" }}>
        <span className="h-5 w-5 flex-none rounded text-center font-mono text-xs leading-5 font-bold"
          style={{ background: cancelled ? "var(--nf)" : "var(--bad)", color: "var(--panel)" }}>
          {cancelled ? "–" : "!"}
        </span>
        <div className="min-w-[260px] flex-1">
          <div className="text-base font-semibold">{title}</div>
          <div className="text-[13px] text-fg2">
            {cancelled ? "Completed stages are kept. Resuming continues from the first unfinished stage." : run.error ?? failed?.error}
            {!cancelled && " Completed stages are kept; resuming starts from the stage that stopped."}
          </div>
          {cancelled && errors.length > 0 && (
            <ul className="m-0 mt-2 list-none p-0 text-[13px]">
              {errors.map((s) => (
                <li key={s.stage}><span className="font-medium text-bad">{s.label} failed:</span> <span className="text-fg2">{s.error}</span></li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex gap-2">
          {verified > 0 && (
            <Link to={`/runs/${run.run_id}/results`}
              className="inline-flex h-8 items-center rounded-md border border-border-strong bg-panel px-3 text-[13px] font-medium text-fg no-underline hover:bg-hover hover:no-underline">
              View partial results
            </Link>
          )}
          <Button variant="primary" onClick={onResume} disabled={resuming}>{resuming ? "Resuming…" : "Resume run"}</Button>
        </div>
      </div>
      {verify && verify.status !== "queued" && verify.total != null && (
        <div className="grid grid-cols-2 text-[13px]">
          <div className="border-r border-border px-5 py-3">
            <div className="text-xs text-fg3">Completed</div>
            <div><span className="font-mono">{verify.done}</span> requirements verified</div>
          </div>
          <div className="px-5 py-3">
            <div className="text-xs text-fg3">Not verified yet</div>
            <div><span className="font-mono">{verify.total - verify.done}</span> requirements</div>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Pipeline() {
  const { runId } = useParams();
  const id = Number(runId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: run, error, isLoading } = useRun(id);
  const { events } = useRunStream(Number.isFinite(id) ? id : null);
  const live = run?.status === "running" || run?.status === "queued";
  const now = useTick(live);
  const tracing = !!run && traceStarted(run);
  const verifyRunning = run ? stageMap(run).verify?.status === "running" : false;
  const { data: results } = useResults(id, { enabled: tracing, live: verifyRunning });
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Lane logs: the snapshot's recent events, then everything streamed since (deduplicated).
  const laneEvents = useMemo(() => {
    const byId = new Map<number, RunEvent>();
    for (const l of run?.lanes ?? []) for (const e of l.log) byId.set(e.event_id, e);
    for (const e of events) byId.set(e.event_id, e);
    const all = [...byId.values()].sort((a, b) => a.event_id - b.event_id);
    return {
      A: all.filter((e) => e.lane === "A").slice(-200),
      B: all.filter((e) => e.lane === "B").slice(-200),
    };
  }, [run?.lanes, events]);

  // Refresh run lists when the status changes (sidebar badges, runs page).
  const status = run?.status;
  useEffect(() => {
    if (status) qc.invalidateQueries({ queryKey: keys.runs });
  }, [status, qc]);

  if (isLoading) return <div className="px-8 py-6 text-[13px] text-fg3">Loading run…</div>;
  if (error || !run) {
    return (
      <div className="px-8 py-6">
        <Alert tone="error" title="Run not found.">{(error as ApiError)?.message}</Alert>
      </div>
    );
  }

  const act = async (path: string, after?: () => void) => {
    setBusy(true);
    setActionError(null);
    try {
      await api.json("POST", `/api/runs/${run.run_id}/${path}`);
      await qc.invalidateQueries({ queryKey: keys.run(run.run_id) });
      after?.();
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const s = stageMap(run);
  const repo = repoLabel(run);
  const a = codeLane(run, repo, now);
  const b = srsLane(run, run.srs_filename, now);
  const showLanes = !ingestDone(run);
  const paused = run.status === "paused";
  const ended = run.status === "failed" || run.status === "cancelled";
  const verified = (results?.requirements ?? []).filter((r) => r.verified_at).length;
  const report = s.index_code?.detail?.report;
  const extracted = s.extract?.status === "done" ? s.extract.done : s.extract?.detail?.phase === "extract" ? s.extract.done : 0;

  return (
    <div className="flex flex-col">
      <Header run={run} now={now} onCancel={() => setConfirm(true)} />
      <div className="flex flex-col gap-4 px-8 pt-6 pb-12">
        {actionError && <Alert tone="error">{actionError}</Alert>}

        {paused && (
          <div role="status" className="tl-in flex flex-wrap items-center gap-4 rounded-lg border border-rev bg-rev-bg px-5 py-4">
            <span className="h-5 w-5 flex-none rounded bg-rev text-center font-mono text-xs leading-5 font-bold text-panel">!</span>
            <div className="min-w-[240px] flex-1">
              <div className="text-base font-semibold">
                {run.review.open
                  ? `Your input is needed: ${plural(run.review.open, "item")} to review`
                  : "Ready to continue: nothing needs a decision"}
              </div>
              <div className="text-[13px] text-fg2">
                Ingestion finished. Tracing starts after you {run.review.open ? "resolve the uncertain, incomplete and duplicate items" : "confirm the extracted requirements"}. Timers are paused until then.
              </div>
            </div>
            <Link to={`/runs/${run.run_id}/review`}
              className="inline-flex h-9 items-center rounded-md bg-rev px-4 font-medium text-panel no-underline hover:no-underline hover:brightness-110">
              Review requirements →
            </Link>
          </div>
        )}

        {ended && <FailurePanel run={run} verified={verified} resuming={busy} onResume={() => act("resume")} />}

        {showLanes ? (
          <>
            <div className="grid grid-cols-4 rounded-lg border border-border bg-panel">
              {[
                { label: "Components parsed", value: s.docstrings?.total ?? "—", color: "var(--fg)" },
                { label: "Relationships found", value: report?.relationships ?? "—", color: "var(--fg)" },
                { label: "Requirements extracted", value: extracted, color: "var(--fg)" },
                { label: "Needing review", value: s.prepare_review?.status === "done" ? run.review.open : "—", color: "var(--rev)" },
              ].map((c, i) => (
                <div key={c.label} className={`px-4 py-3 ${i < 3 ? "border-r border-border" : ""}`}>
                  <div className="text-xs text-fg3">{c.label}</div>
                  <div className="font-mono text-xl leading-[1.3] font-medium" style={{ color: c.color }}>{c.value}</div>
                </div>
              ))}
            </div>
            <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(420px,1fr))" }}>
              <Lane lane={a} events={laneEvents.A} />
              <Lane lane={b} events={laneEvents.B} />
            </div>
          </>
        ) : (
          !tracing && (
            <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(320px,1fr))" }}>
              <LaneSummary lane={a} text={
                <>{report?.components ?? s.docstrings?.total} components · {report?.relationships ?? 0} relationships · {report?.docstrings?.generated ?? 0} docstrings written · indexed</>
              } />
              <LaneSummary lane={b} text={
                <>{s.extract?.detail?.candidates ?? "?"} candidates · {s.prepare_review?.detail?.requirements ?? extracted} requirements extracted
                  {run.review.open ? <> · <span className="text-rev">{run.review.open} need review</span></> : " · nothing needs review"}</>
              } />
            </div>
          )
        )}

        {paused && (
          <section className="rounded-lg border border-border bg-panel">
            <div className="border-b border-border px-4 py-3 text-sm font-semibold">Queued after review</div>
            <div className="grid grid-cols-3">
              <div className="border-r border-border px-4 py-3">
                <div className="text-[13px] font-medium">Search agent</div>
                <div className="text-xs text-fg3">Candidate code for each requirement · about a minute</div>
              </div>
              <div className="border-r border-border px-4 py-3">
                <div className="text-[13px] font-medium">Mapping agent</div>
                <div className="text-xs text-fg3">Direct + supporting subgraphs · seconds</div>
              </div>
              <div className="px-4 py-3">
                <div className="text-[13px] font-medium">Verifier agent</div>
                <div className="text-xs text-fg3">~20 s per requirement on {run.models?.verifier ?? "the verifier model"}</div>
              </div>
            </div>
          </section>
        )}

        {tracing && (
          <>
            <div className="grid grid-cols-3 gap-4">
              {agentCards(run, run.models?.verifier).map((c) => <Agent key={c.name} card={c} />)}
            </div>
            <VerifiedStream run={run} rows={results?.requirements ?? []} />
            {run.status === "completed" && (
              <div className="flex justify-end">
                <Button variant="primary" onClick={() => navigate(`/runs/${run.run_id}/results`)}>Open results →</Button>
              </div>
            )}
          </>
        )}
      </div>

      {confirm && (
        <ConfirmDialog
          title={`Cancel Run #${run.run_id}?`}
          confirmLabel="Cancel run"
          cancelLabel="Keep running"
          destructive
          busy={busy}
          onCancel={() => setConfirm(false)}
          onConfirm={() => act("cancel", () => setConfirm(false))}
        >
          Work completed so far is kept: generated docstrings, extracted requirements and any verdicts. You can resume
          the run later; it continues from the first unfinished stage.
        </ConfirmDialog>
      )}
    </div>
  );
}
