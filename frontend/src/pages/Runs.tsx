import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useRuns } from "../api/hooks";
import type { RunCard } from "../api/types";
import { PageHeader } from "../components/layout/AppShell";
import { Alert, Segmented } from "../components/ui/Form";
import { XIcon } from "../components/ui/Icon";
import { ConfirmDialog } from "../components/ui/Dialog";
import { StatusChip } from "../components/ui/Status";
import { clock, dateTime } from "../lib/format";
import {
  commitLabel, filterRuns, repoLabel, runDuration, runHref, runResult, runSubtitle, RUN_FILTERS, type RunFilter,
} from "../lib/runs";
import { runMeta } from "../lib/status";

const COLS = "minmax(200px,1.4fr) minmax(130px,1fr) minmax(170px,1.1fr) 110px 150px minmax(150px,1fr) 72px 28px";

function NewRunButton({ large }: { large?: boolean }) {
  return (
    <Link
      to="/new"
      className={
        "inline-flex items-center gap-2 rounded-md bg-accent px-3.5 font-medium text-accent-fg no-underline hover:no-underline hover:brightness-110 " +
        (large ? "h-9 px-4 text-sm" : "h-8 text-[13px]")
      }
    >
      <span className="text-base leading-none">+</span>New traceability run
    </Link>
  );
}

/** Re-render every second while something runs (durations tick). */
function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [active]);
  return now;
}

function RunRow({ run, now, onDelete }: { run: RunCard; now: number; onDelete: (run: RunCard) => void }) {
  const navigate = useNavigate();
  const meta = runMeta(run.status);
  const result = runResult(run);
  const canDelete = run.status !== "running";
  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => navigate(runHref(run))}
      onKeyDown={(e) => e.key === "Enter" && navigate(runHref(run))}
      className="grid min-h-[52px] cursor-pointer items-center gap-4 border-b border-border px-4 text-[13px] last:border-b-0 hover:bg-subtle"
      style={{ gridTemplateColumns: COLS }}
    >
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{run.name}</span>
        <span className="text-xs text-fg3">{runSubtitle(run)}</span>
      </span>
      <span className="truncate font-mono text-xs text-fg2">{run.srs_filename}</span>
      <span className="truncate font-mono text-xs text-fg2">
        {repoLabel(run)} <span className="text-fg3">@ {commitLabel(run)}</span>
      </span>
      <span className="text-xs text-fg2">{dateTime(run.started_at ?? run.created_at)}</span>
      <span>
        <StatusChip meta={{ ...meta, g: "" }} />
      </span>
      <span className="flex min-w-0 flex-col gap-1">
        <span className="truncate text-xs text-fg2" title={run.error ?? undefined}>{result.text}</span>
        {result.bar != null && (
          <span className="flex h-1 overflow-hidden rounded-sm bg-hover">
            <span style={{ width: `${Math.round(result.bar * 100)}%`, background: meta.c }} />
          </span>
        )}
      </span>
      <span className="text-right font-mono text-xs text-fg2">{clock(runDuration(run, now))}</span>
      <span className="flex justify-end">
        {canDelete && (
          <button
            aria-label={`Delete run ${run.run_id}`}
            title="Delete run"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(run);
            }}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent text-fg3 hover:border-border-strong hover:text-bad"
          ><XIcon /></button>
        )}
      </span>
    </div>
  );
}

function Loading() {
  return (
    <div className="flex flex-col gap-4 px-8 py-6" aria-busy="true" aria-label="Loading runs">
      <div className="tl-skeleton h-8 w-[360px] max-w-full rounded-md" />
      <div className="rounded-lg border border-border bg-panel">
        <div className="h-9 border-b border-border" />
        {["70%", "55%", "65%", "50%", "72%", "60%"].map((w) => (
          <div key={w} className="grid h-[52px] items-center gap-4 border-b border-border px-4 last:border-b-0"
            style={{ gridTemplateColumns: "1.4fr 1fr 1.1fr 110px 150px 1fr 80px" }}>
            <span className="tl-skeleton h-2.5 rounded-[3px]" style={{ width: w }} />
            <span className="h-2.5 w-[70%] rounded-[3px] bg-subtle" />
            <span className="h-2.5 w-[80%] rounded-[3px] bg-subtle" />
            <span className="h-2.5 w-[60%] rounded-[3px] bg-subtle" />
            <span className="h-5 w-[90px] rounded bg-subtle" />
            <span className="h-2.5 w-[75%] rounded-[3px] bg-subtle" />
            <span className="h-2.5 w-10 justify-self-end rounded-[3px] bg-subtle" />
          </div>
        ))}
      </div>
    </div>
  );
}

const STEPS = [
  ["Upload an SRS and a codebase", "PDF, DOCX or text, plus a ZIP, folder or GitHub URL. Docstrings and requirements are extracted in parallel."],
  ["Review the extracted requirements", "The run pauses once so you can confirm uncertain, incomplete or duplicate items."],
  ["Inspect verdicts and evidence", "Each requirement gets a verdict with line-level citations you can accept or override."],
];

function Empty() {
  return (
    <div className="tl-in flex justify-center px-8 py-16">
      <div className="flex w-full max-w-[640px] flex-col gap-6">
        <div>
          <h2 className="m-0 mb-2 text-2xl font-semibold tracking-[-0.015em]">No runs yet</h2>
          <p className="m-0 text-base leading-relaxed text-pretty text-fg2">
            Tracelight links each requirement in your SRS to the code that implements it, and shows the lines that
            prove it. Everything runs locally on your Ollama models.
          </p>
        </div>
        <ol className="m-0 list-none rounded-lg border border-border bg-panel p-0">
          {STEPS.map(([title, text], i) => (
            <li key={title} className="grid gap-3 border-b border-border p-4 last:border-b-0" style={{ gridTemplateColumns: "32px 1fr" }}>
              <span className="font-mono text-xs leading-6 font-medium text-fg3">{String(i + 1).padStart(2, "0")}</span>
              <span>
                <span className="block font-medium">{title}</span>
                <span className="text-[13px] text-fg2">{text}</span>
              </span>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap items-center gap-4">
          <NewRunButton large />
          <span className="text-[13px] text-fg3">
            Most of the time goes into docstring generation (about 40 s per component on a local model).
          </span>
        </div>
      </div>
    </div>
  );
}

export function Runs() {
  const { data: runs, isLoading, error } = useRuns();
  const [filter, setFilter] = useState<RunFilter>("all");
  const [q, setQ] = useState("");
  const qc = useQueryClient();
  const now = useNow(!!runs?.some((r) => r.status === "running"));
  const [confirmDelete, setConfirmDelete] = useState<RunCard | null>(null);
  const del = useMutation({
    mutationFn: (run: RunCard) => api.json("DELETE", `/api/runs/${run.run_id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: keys.runs });
      setConfirmDelete(null);
    },
  });

  const onDelete = (run: RunCard) => {
    del.reset();
    setConfirmDelete(run);
  };

  const rows = runs ? filterRuns(runs, filter, q) : [];
  return (
    <div className="flex flex-col">
      <PageHeader
        title="Runs"
        subtitle="Each run traces one SRS against one codebase snapshot."
        actions={runs && runs.length > 0 ? <NewRunButton /> : undefined}
      />
      {error ? (
        <div className="px-8 py-6">
          <Alert tone="error" title="Could not load runs.">{(error as ApiError).message}</Alert>
        </div>
      ) : isLoading || !runs ? (
        <Loading />
      ) : runs.length === 0 ? (
        <Empty />
      ) : (
        <div className="tl-in flex flex-col gap-4 px-8 py-6">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex h-8 max-w-[360px] min-w-[220px] flex-1 items-center gap-2 rounded-md border border-border-strong bg-panel px-2.5">
              <span aria-hidden="true" className="h-2.5 w-2.5 flex-none rounded-full border-[1.5px] border-fg3" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search runs, files or commits"
                aria-label="Search runs"
                className="flex-1 border-0 bg-transparent text-[13px] text-fg outline-none placeholder:text-fg3"
              />
            </label>
            <Segmented
              label="Filter runs"
              size="md"
              value={filter}
              onChange={setFilter}
              options={RUN_FILTERS.map((f) => ({
                id: f.id,
                label: (
                  <>
                    {f.label}
                    <span className="font-mono text-fg3">{filterRuns(runs, f.id, "").length}</span>
                  </>
                ),
              }))}
            />
          </div>
          <div className="overflow-x-auto rounded-lg border border-border bg-panel">
            <div className="min-w-[1000px]">
              <div className="grid h-9 items-center gap-4 border-b border-border px-4 text-xs font-medium text-fg3" style={{ gridTemplateColumns: COLS }}>
                <span>Run</span>
                <span>SRS file</span>
                <span>Repository @ commit</span>
                <span>Started</span>
                <span>Status</span>
                <span>Result</span>
                <span className="text-right">Duration</span>
                <span />
              </div>
              {rows.map((r) => (
                <RunRow key={r.run_id} run={r} now={now} onDelete={onDelete} />
              ))}
              {rows.length === 0 && (
                <div className="px-4 py-8 text-center text-[13px] text-fg3">
                  No runs match{q ? ` “${q}”` : " this filter"}.{" "}
                  <button
                    onClick={() => {
                      setQ("");
                      setFilter("all");
                    }}
                    className="cursor-pointer border-0 bg-transparent p-0 text-accent"
                  >
                    Show all runs
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="text-xs text-fg3">
            Runs are stored in the local database. Deleting a run removes its files and results permanently.
          </div>
        </div>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete Run #${confirmDelete.run_id}?`}
          confirmLabel="Delete run"
          cancelLabel="Keep run"
          destructive
          busy={del.isPending}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => del.mutate(confirmDelete)}
        >
          <p className="m-0">
            <span className="font-medium text-fg">{confirmDelete.name}</span> and everything it produced will be removed:
            the uploaded files, the working copy, extracted requirements, mappings, verdicts and your overrides.
            This can’t be undone.
          </p>
          {del.error && (
            <div className="mt-3"><Alert tone="error" title="Delete failed.">{(del.error as ApiError).message}</Alert></div>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
