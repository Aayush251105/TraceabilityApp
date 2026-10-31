import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { useResults, useRun } from "../api/hooks";
import type { CodeView as CodeViewData, ComponentDetail } from "../api/types";
import { CodeBlock } from "../components/ui/Code";
import { Alert, Segmented } from "../components/ui/Form";
import { StatusChip } from "../components/ui/Status";
import { plural } from "../lib/format";
import { verdictMeta } from "../lib/status";

/** The folder every file path starts with ("library_system/"), so the tree shows paths below it. */
export function commonRoot(paths: string[]): string {
  if (!paths.length) return "";
  const split = paths.map((p) => p.split("/").slice(0, -1));
  const first = split[0];
  let n = 0;
  while (n < first.length && split.every((s) => s[n] === first[n])) n++;
  return n ? `${first.slice(0, n).join("/")}/` : "";
}

export function CodeView() {
  const { runId } = useParams();
  const id = Number(runId);
  const [params, setParams] = useSearchParams();
  const { data: run } = useRun(id);
  const { data: results } = useResults(id);
  const { data, isLoading, error } = useQuery({ queryKey: ["code", id], queryFn: () => api.get<CodeViewData>(`/api/runs/${id}/code`) });
  const [filter, setFilter] = useState<"all" | "untraced">("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const selectedId = params.get("component");
  const files = data?.files ?? [];
  const all = useMemo(() => files.flatMap((f) => f.components.map((c) => ({ ...c, path: f.path }))), [files]);
  const selected = all.find((c) => c.component_id === selectedId) ?? all.find((c) => c.traced) ?? all[0];
  const root = commonRoot(files.map((f) => f.path));
  const titles = useMemo(() => Object.fromEntries((results?.requirements ?? []).map((r) => [r.requirement_id, r.title])), [results]);
  const untracedCount = all.filter((c) => !c.traced).length;

  // Open the selected component's file.
  useEffect(() => {
    if (selected) setOpen((o) => (o[selected.path] ? o : { ...o, [selected.path]: true }));
  }, [selected?.path]);

  const { data: comp, isLoading: compLoading } = useQuery({
    queryKey: ["component", id, selected?.component_id],
    queryFn: () => api.get<ComponentDetail>(`/api/runs/${id}/code/component?component_id=${encodeURIComponent(selected!.component_id)}`),
    enabled: !!selected,
  });

  const pick = (cid: string) => setParams({ component: cid }, { replace: true });
  const relationships = run?.stages?.find((s) => s.stage === "index_code")?.detail?.report?.relationships;
  const repoName = root.replace(/\/$/, "") || run?.repo_id?.replace(/^run-\d+-/, "") || "Repository";

  if (isLoading) return <div className="px-8 py-6 text-[13px] text-fg3">Loading code…</div>;
  if (error) return <div className="px-8 py-6"><Alert tone="error" title="Could not load the code view.">{(error as ApiError).message}</Alert></div>;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border bg-panel px-8 pt-5 pb-4">
        <div>
          <div className="mb-0.5 text-xs text-fg3">
            <Link to={`/runs/${id}/results`} className="text-fg3">Run #{id}</Link> / Code view
          </div>
          <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">{repoName}</h1>
          <div className="text-[13px] text-fg3">
            {data && data.components > 0 ? (
              <>
                <span className="font-mono text-fg2">{data.traced}</span> of <span className="font-mono">{data.components}</span> components linked to at least one requirement
                {" · "}{plural(files.length, "file")}{relationships != null ? ` · ${relationships} relationships` : ""}
              </>
            ) : "The code is indexed after DocAgent finishes; links appear after mapping."}
          </div>
        </div>
        {all.length > 0 && (
          <Segmented label="Code filter" size="md" value={filter} onChange={setFilter}
            options={[{ id: "all", label: "All code" }, { id: "untraced", label: <>Untraced code <span className="font-mono text-fg3">{untracedCount}</span></> }]} />
        )}
      </header>

      {all.length === 0 ? (
        <div className="px-8 py-6"><Alert tone="info">No code components yet. <Link to={`/runs/${id}/pipeline`}>Watch the pipeline →</Link></Alert></div>
      ) : (
        <div className="grid min-h-0 flex-1" style={{ gridTemplateColumns: "minmax(260px,320px) minmax(0,1fr)" }}>
          <nav aria-label="Repository files" className="overflow-y-auto border-r border-border bg-panel py-2">
            <div className="px-4 pt-1.5 pb-2 font-mono text-xs font-medium text-fg3">{root || "./"}</div>
            {files.map((f) => {
              const shown = filter === "untraced" ? f.components.filter((c) => !c.traced) : f.components;
              if (filter === "untraced" && shown.length === 0) return null;
              const isOpen = !!open[f.path] || filter === "untraced";
              const pct = f.total ? f.traced / f.total : 0;
              return (
                <div key={f.path}>
                  <button onClick={() => setOpen((o) => ({ ...o, [f.path]: !isOpen }))} aria-expanded={isOpen}
                    className="grid h-[30px] w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-4 text-left hover:bg-subtle"
                    style={{ gridTemplateColumns: "12px minmax(0,1fr) 44px 40px" }}>
                    <span className="inline-block text-[8px] text-fg3 transition-transform duration-150 ease-out" style={{ transform: isOpen ? "rotate(90deg)" : "none" }}>▶</span>
                    <span className="truncate font-mono text-[13px] text-fg" title={f.path}>{f.path.slice(root.length)}</span>
                    <span className="flex h-1 overflow-hidden rounded-sm bg-hover">
                      <span style={{ width: `${pct * 100}%`, background: pct === 1 ? "var(--ok)" : pct === 0 ? "var(--fg3)" : "var(--part)" }} />
                    </span>
                    <span className="text-right font-mono text-[11px] text-fg3">{f.traced}/{f.total}</span>
                  </button>
                  {isOpen && (
                    <div role="group">
                      {shown.map((c) => {
                        const cur = c.component_id === selected?.component_id;
                        return (
                          <button key={c.component_id} onClick={() => pick(c.component_id)} aria-current={cur ? "true" : undefined}
                            className="grid h-7 w-full cursor-pointer items-center gap-2 border-0 pr-4 pl-9 text-left hover:bg-subtle"
                            style={{ gridTemplateColumns: "10px minmax(0,1fr) auto", background: cur ? "var(--hover)" : "transparent" }}>
                            <span className="h-2 w-2 rounded-full border-[1.5px]" style={{ borderColor: c.traced ? "var(--ok)" : "var(--fg3)", background: c.traced ? "var(--ok)" : "transparent" }} />
                            <span className="truncate font-mono text-xs" style={{ color: c.traced ? "var(--fg)" : "var(--fg2)" }}>{c.name}</span>
                            <span className="font-mono text-[11px] text-fg3">{c.requirements.length || ""}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            <div className="mt-2 flex gap-4 border-t border-border p-4 text-xs text-fg3">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full border-[1.5px] border-ok bg-ok" />Traced</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full border-[1.5px] border-fg3" />Untraced</span>
            </div>
          </nav>

          {selected && (
            <div className="flex min-w-0 flex-col gap-4 px-8 pt-5 pb-12">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="m-0 font-mono text-xl font-semibold tracking-[-0.01em]">{selected.name}</h2>
                  <div className="font-mono text-xs text-fg3">{selected.path} · lines {selected.start_line}–{selected.end_line} · {selected.type}</div>
                </div>
                <span className="inline-flex h-6 items-center gap-1.5 rounded pr-2.5 pl-2 text-xs font-medium"
                  style={{ background: selected.traced ? "var(--ok-bg)" : "var(--nf-bg)", color: selected.traced ? "var(--ok)" : "var(--fg2)" }}>
                  <span className="h-2.5 w-2.5 rounded-full border-[1.5px]" style={{ borderColor: "currentColor", background: selected.traced ? "var(--ok)" : "transparent" }} />
                  {selected.traced ? `Traced · ${plural(selected.requirements.length, "requirement")}` : "Untraced"}
                </span>
              </div>

              <section aria-label="Requirements" className="rounded-lg border border-border bg-panel">
                <div className="flex justify-between border-b border-border px-4 py-3">
                  <h3 className="m-0 text-sm font-semibold">Requirements implemented</h3>
                  <span className="text-xs text-fg3">{selected.traced ? `${selected.requirements.length} linked` : "none"}</span>
                </div>
                {selected.traced ? (
                  selected.requirements.map((r) => (
                    <Link key={r.requirement_id + r.role} to={`/runs/${id}/requirements/${encodeURIComponent(r.requirement_id)}`}
                      className="grid min-h-[42px] items-center gap-3 border-b border-border px-4 text-[13px] text-fg no-underline last:border-b-0 hover:bg-subtle hover:no-underline"
                      style={{ gridTemplateColumns: "80px minmax(0,1fr) 96px 230px" }}>
                      <span className="font-mono text-xs font-medium">{r.requirement_id}</span>
                      <span className="truncate">{titles[r.requirement_id] ?? ""}</span>
                      <span className="font-mono text-[10px] font-semibold tracking-[.04em] text-fg3">{r.role.toUpperCase()}</span>
                      <span><StatusChip meta={verdictMeta(r.verdict)} /></span>
                    </Link>
                  ))
                ) : (
                  <div className="tl-in flex flex-col gap-2.5 p-4">
                    <div className="font-medium">No requirement maps to this component</div>
                    <div className="max-w-[640px] text-[13px] text-pretty text-fg2">
                      That can mean it is a helper with no user-facing behaviour, dead code, or behaviour the SRS doesn’t describe.
                      {selected.best_candidate ? (
                        <> Search ranked it below the mapping cut-off for every requirement; its best match was{" "}
                          <Link to={`/runs/${id}/requirements/${encodeURIComponent(selected.best_candidate.requirement_id)}`} className="font-mono">
                            {selected.best_candidate.requirement_id}
                          </Link>
                          {titles[selected.best_candidate.requirement_id] ? ` (${titles[selected.best_candidate.requirement_id]})` : ""}
                          {selected.best_candidate.rank != null ? `, at rank #${selected.best_candidate.rank}` : ""}.</>
                      ) : " No requirement ranked it among its search candidates."}
                    </div>
                  </div>
                )}
              </section>

              {compLoading ? (
                <div className="text-xs text-fg3">Loading code…</div>
              ) : comp && (
                <>
                  {Object.entries(comp.docstrings).map(([kind, text]) => (
                    <div key={kind} className="rounded-md border border-dashed border-border-strong bg-subtle px-3 py-2.5">
                      <div className="mb-1 font-mono text-[11px] font-medium text-fg3">
                        {kind === "generated" ? "GENERATED DOCUMENTATION, NOT EVIDENCE" : "EXISTING DOCSTRING, NOT EVIDENCE"}
                      </div>
                      <div className="max-h-[160px] overflow-y-auto text-[13px] text-pretty whitespace-pre-line text-fg2">{text.trim()}</div>
                    </div>
                  ))}
                  {comp.code.length ? <CodeBlock lines={comp.code} /> : <div className="text-xs text-fg3">The source file is not available.</div>}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
