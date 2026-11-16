import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { useResults } from "../api/hooks";
import type { SearchMatch, SearchResult } from "../api/types";
import { Alert } from "../components/ui/Form";
import { SearchIcon, XIcon } from "../components/ui/Icon";
import { Glyph, StatusChip } from "../components/ui/Status";
import { shortComponent } from "../lib/format";
import { typeLabel } from "../lib/results";
import { verdictMeta } from "../lib/status";

const STOP = new Set(["the", "and", "for", "with", "that", "this", "shall", "system", "from", "are", "can", "into", "its"]);

/** Words worth highlighting (3+ letters, not filler). */
export function queryTerms(q: string): string[] {
  return Array.from(new Set(q.toLowerCase().match(/[a-z0-9_]{3,}/g) ?? [])).filter((w) => !STOP.has(w));
}

/** Text with the query's words marked. */
export function Highlight({ text, terms }: { text: string; terms: string[] }): ReactNode {
  if (!terms.length || !text) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) =>
    i % 2 ? <mark key={i} className="rounded-[2px] bg-part-bg px-px text-fg">{part}</mark> : <span key={i}>{part}</span>);
}

function MatchBadges({ match }: { match: SearchMatch }) {
  const labels = [
    match.exact_id && "exact ID",
    match.keyword && "keyword",
    match.semantic && "meaning",
    match.via_docstring && "via docstring",
  ].filter(Boolean) as string[];
  return (
    <span className="flex flex-wrap gap-1">
      {labels.map((l) => (
        <span key={l} className="rounded-[3px] bg-hover px-1.5 font-mono text-[10px] leading-4 text-fg3">{l}</span>
      ))}
    </span>
  );
}

export function Search() {
  const { runId } = useParams();
  const id = Number(runId);
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  const input = useRef<HTMLInputElement>(null);
  const { data: results } = useResults(id);

  useEffect(() => setDraft(q), [q]);

  // Search as you type (debounced); the query lives in the URL.
  useEffect(() => {
    const t = setTimeout(() => {
      if (draft.trim() !== q) setParams(draft.trim() ? { q: draft.trim() } : {}, { replace: true });
    }, 400);
    return () => clearTimeout(t);
  }, [draft]);

  // "/" focuses the search box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (e.key === "/" && tag !== "input" && tag !== "textarea") {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { data, isFetching, error } = useQuery({
    queryKey: ["search", id, q],
    queryFn: () => api.get<SearchResult>(`/api/runs/${id}/search?q=${encodeURIComponent(q)}&limit=10`),
    enabled: !!q,
    placeholderData: (prev) => prev,
  });

  const terms = queryTerms(q);
  const examples = (results?.requirements ?? []).slice(0, 4).map((r) => r.title).filter(Boolean);
  const noScope = data?.scope && !data.scope.requirements && !data.scope.code;

  return (
    <div className="flex flex-col">
      <header className="border-b border-border bg-panel px-8 pt-5 pb-5">
        <div className="mb-0.5 text-xs text-fg3">
          <Link to={`/runs/${id}/results`} className="text-fg3">Run #{id}</Link> / Search
        </div>
        <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">Search this run</h1>
        <div className="text-[13px] text-fg3">Find a feature by keyword or sentence, then the code that implements it. Matches by wording and by meaning.</div>
        <form className="mt-4 flex max-w-[760px] items-center gap-2.5 rounded-lg border border-border-strong bg-panel px-3 focus-within:border-accent"
          onSubmit={(e) => { e.preventDefault(); setParams(draft.trim() ? { q: draft.trim() } : {}, { replace: true }); }}>
          <span className="text-fg3"><SearchIcon size={16} /></span>
          <input ref={input} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Search requirements and code"
            placeholder="e.g. renew a loan, overdue fines, FR-016"
            className="h-11 flex-1 border-0 bg-transparent text-[15px] text-fg outline-none placeholder:text-fg3" />
          {isFetching && <span className="h-3.5 w-3.5 rounded-full border-[1.5px] border-accent" style={{ borderRightColor: "transparent", animation: "tlSpin 800ms linear infinite" }} />}
          {draft && (
            <button type="button" aria-label="Clear search" onClick={() => { setDraft(""); setParams({}, { replace: true }); input.current?.focus(); }}
              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-fg3 hover:bg-hover hover:text-fg"><XIcon /></button>
          )}
          <kbd className="rounded-[3px] border border-b-2 border-border-strong px-[5px] font-mono text-[11px] text-fg3">/</kbd>
        </form>
      </header>

      <div className="flex max-w-[1280px] flex-col gap-4 px-8 pt-6 pb-12">
        {error && <Alert tone="error" title="Search failed.">{(error as ApiError).message}</Alert>}
        {!q && (
          <div className="text-[13px] text-fg3">
            {examples.length > 0 ? (
              <>Try{" "}
                {examples.map((t, i) => (
                  <span key={t}>{i > 0 && ", "}
                    <button onClick={() => { setDraft(t!); setParams({ q: t! }, { replace: true }); }} className="cursor-pointer border-0 bg-transparent p-0 text-accent">“{t}”</button>
                  </span>
                ))}
                {" "}or a requirement ID.</>
            ) : "Type what you are looking for: a feature, a rule, a requirement ID."}
          </div>
        )}
        {noScope && <Alert tone="info">Nothing to search yet: requirements and code are indexed as the run progresses. <Link to={`/runs/${id}/pipeline`}>Watch the pipeline →</Link></Alert>}

        {q && data && !noScope && (
          <div className="grid items-start gap-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(440px,1fr))" }}>
            {/* Requirements */}
            <section aria-labelledby="sr-req" className="rounded-lg border border-border bg-panel">
              <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
                <h2 id="sr-req" className="m-0 text-sm font-semibold">Requirements</h2>
                <span className="text-xs text-fg3">{data.scope?.requirements === false ? "not indexed yet" : `${data.requirements.length} found`}</span>
              </div>
              {data.requirements.length === 0 && <div className="px-4 py-6 text-center text-[13px] text-fg3">No requirement matches “{q}”.</div>}
              {data.requirements.map((r) => {
                const direct = r.components.filter((c) => c.role === "direct");
                const supporting = r.components.length - direct.length;
                return (
                  <div key={r.requirement_id} className="tl-in flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link to={`/runs/${id}/requirements/${encodeURIComponent(r.requirement_id)}`} className="font-mono text-xs font-medium">{r.requirement_id}</Link>
                      <Link to={`/runs/${id}/requirements/${encodeURIComponent(r.requirement_id)}`} className="min-w-0 flex-1 truncate text-sm font-medium text-fg">
                        <Highlight text={r.title ?? ""} terms={terms} />
                      </Link>
                      <StatusChip meta={verdictMeta(r.verdict)} />
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <MatchBadges match={r.match} />
                      {r.type && <span className="text-xs text-fg3">{typeLabel(r.type)}</span>}
                    </div>
                    {r.components.length > 0 ? (
                      <div className="flex flex-col gap-1">
                        <div className="text-xs text-fg3">Implemented by</div>
                        {direct.map((c) => (
                          <Link key={c.component_id} to={`/runs/${id}/code?component=${encodeURIComponent(c.component_id)}`}
                            className="flex items-baseline justify-between gap-3 rounded-[5px] bg-subtle px-2 py-1 font-mono text-xs text-fg no-underline hover:bg-hover hover:no-underline">
                            <span className="truncate font-medium">{shortComponent(c.component_id)}</span>
                            <span className="flex-none text-fg3">{c.path.split("/").pop()}:{c.start_line}–{c.end_line}</span>
                          </Link>
                        ))}
                        {supporting > 0 && <span className="text-xs text-fg3">+ {supporting} supporting component{supporting > 1 ? "s" : ""}</span>}
                      </div>
                    ) : (
                      <div className="text-xs text-fg3">No code mapped to this requirement{r.verdict === "pending" ? " yet" : ""}.</div>
                    )}
                  </div>
                );
              })}
            </section>

            {/* Code */}
            <section aria-labelledby="sr-code" className="rounded-lg border border-border bg-panel">
              <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
                <h2 id="sr-code" className="m-0 text-sm font-semibold">Code</h2>
                <span className="text-xs text-fg3">{data.scope?.code === false ? "not indexed yet" : `${data.components.length} found`}</span>
              </div>
              {data.components.length === 0 && <div className="px-4 py-6 text-center text-[13px] text-fg3">No code matches “{q}”.</div>}
              {data.components.map((c) => (
                <div key={c.component_id} className="tl-in flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <Link to={`/runs/${id}/code?component=${encodeURIComponent(c.component_id)}`} className="min-w-0 truncate font-mono text-[13px] font-medium text-fg">
                      <Highlight text={shortComponent(c.component_id)} terms={terms} />
                    </Link>
                    <span className="flex-none font-mono text-xs text-fg3">{c.path}:{c.start_line}–{c.end_line}</span>
                  </div>
                  <MatchBadges match={c.match} />
                  {c.requirements.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {c.requirements.slice(0, 8).map((r) => {
                        const m = verdictMeta(r.verdict);
                        return (
                          <Link key={r.requirement_id + r.role} to={`/runs/${id}/requirements/${encodeURIComponent(r.requirement_id)}`}
                            title={`${r.title ?? ""} · ${r.role} · ${m.label}`}
                            className="inline-flex h-[22px] items-center gap-1.5 rounded border border-border px-1.5 font-mono text-[11px] text-fg no-underline hover:border-border-strong hover:no-underline">
                            <Glyph meta={m} size={10} />{r.requirement_id}
                            {r.role === "direct" && <span className="text-fg3">direct</span>}
                          </Link>
                        );
                      })}
                      {c.requirements.length > 8 && <span className="text-xs text-fg3">+{c.requirements.length - 8} more</span>}
                    </div>
                  ) : (
                    <div className="text-xs text-fg3">Not linked to any requirement.</div>
                  )}
                </div>
              ))}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
