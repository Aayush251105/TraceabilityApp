import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { useResults } from "../api/hooks";
import type { AskComponent, AskIntent, AskResult, SearchMatch, SearchResult } from "../api/types";
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

const codeHref = (id: number, componentId: string) => `/runs/${id}/code?component=${encodeURIComponent(componentId)}`;
const reqHref = (id: number, requirementId: string) => `/runs/${id}/requirements/${encodeURIComponent(requirementId)}`;

/** Requirement chips (with verdict glyph) for one component. */
function RequirementChips({ id, requirements }: { id: number; requirements: { requirement_id: string; role: string | null; title?: string | null; verdict: string }[] }) {
  if (!requirements.length) return <div className="text-xs text-fg3">Not linked to any requirement.</div>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {requirements.slice(0, 8).map((r) => {
        const m = verdictMeta(r.verdict);
        return (
          <Link key={r.requirement_id + r.role} to={reqHref(id, r.requirement_id)}
            title={`${r.title ?? ""} · ${r.role} · ${m.label}`}
            className="inline-flex h-[22px] items-center gap-1.5 rounded border border-border px-1.5 font-mono text-[11px] text-fg no-underline hover:border-border-strong hover:no-underline">
            <Glyph meta={m} size={10} />{r.requirement_id}
            {r.role === "direct" && <span className="text-fg3">direct</span>}
          </Link>
        );
      })}
      {requirements.length > 8 && <span className="text-xs text-fg3">+{requirements.length - 8} more</span>}
    </div>
  );
}

/** Code links for one requirement: direct ones listed, supporting ones counted. */
function ImplementedBy({ id, components, verdict }: { id: number; components: { component_id: string; role: string | null; path: string; start_line: number; end_line: number }[]; verdict: string }) {
  if (!components.length) return <div className="text-xs text-fg3">No code mapped to this requirement{verdict === "pending" ? " yet" : ""}.</div>;
  const direct = components.filter((c) => c.role === "direct");
  const supporting = components.length - direct.length;
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-fg3">Implemented by</div>
      {direct.map((c) => (
        <Link key={c.component_id} to={codeHref(id, c.component_id)}
          className="flex items-baseline justify-between gap-3 rounded-[5px] bg-subtle px-2 py-1 font-mono text-xs text-fg no-underline hover:bg-hover hover:no-underline">
          <span className="truncate font-medium">{shortComponent(c.component_id)}</span>
          <span className="flex-none text-fg3">{c.path.split("/").pop()}:{c.start_line}–{c.end_line}</span>
        </Link>
      ))}
      {supporting > 0 && <span className="text-xs text-fg3">+ {supporting} supporting component{supporting > 1 ? "s" : ""}</span>}
    </div>
  );
}

function SectionHead({ id, title, count }: { id: string; title: string; count: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
      <h2 id={id} className="m-0 text-sm font-semibold">{title}</h2>
      <span className="text-xs text-fg3">{count}</span>
    </div>
  );
}

/** The two-column search result (requirements | code). */
function SearchResults({ id, q, data }: { id: number; q: string; data: SearchResult }) {
  const terms = queryTerms(q);
  return (
    <div className="grid items-start gap-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(440px,1fr))" }}>
      <section aria-labelledby="sr-req" className="rounded-lg border border-border bg-panel">
        <SectionHead id="sr-req" title="Requirements" count={data.scope?.requirements === false ? "not indexed yet" : `${data.requirements.length} found`} />
        {data.requirements.length === 0 && <div className="px-4 py-6 text-center text-[13px] text-fg3">No requirement matches “{q}”.</div>}
        {data.requirements.map((r) => (
          <div key={r.requirement_id} className="tl-in flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link to={reqHref(id, r.requirement_id)} className="font-mono text-xs font-medium">{r.requirement_id}</Link>
              <Link to={reqHref(id, r.requirement_id)} className="min-w-0 flex-1 truncate text-sm font-medium text-fg">
                <Highlight text={r.title ?? ""} terms={terms} />
              </Link>
              <StatusChip meta={verdictMeta(r.verdict)} />
            </div>
            <div className="flex items-center justify-between gap-3">
              <MatchBadges match={r.match} />
              {r.type && <span className="text-xs text-fg3">{typeLabel(r.type)}</span>}
            </div>
            <ImplementedBy id={id} components={r.components} verdict={r.verdict} />
          </div>
        ))}
      </section>

      <section aria-labelledby="sr-code" className="rounded-lg border border-border bg-panel">
        <SectionHead id="sr-code" title="Code" count={data.scope?.code === false ? "not indexed yet" : `${data.components.length} found`} />
        {data.components.length === 0 && <div className="px-4 py-6 text-center text-[13px] text-fg3">No code matches “{q}”.</div>}
        {data.components.map((c) => (
          <div key={c.component_id} className="tl-in flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
            <div className="flex items-baseline justify-between gap-3">
              <Link to={codeHref(id, c.component_id)} className="min-w-0 truncate font-mono text-[13px] font-medium text-fg">
                <Highlight text={shortComponent(c.component_id)} terms={terms} />
              </Link>
              <span className="flex-none font-mono text-xs text-fg3">{c.path}:{c.start_line}–{c.end_line}</span>
            </div>
            <MatchBadges match={c.match} />
            <RequirementChips id={id} requirements={c.requirements} />
          </div>
        ))}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ask
// ---------------------------------------------------------------------------

const INTENT_LABEL: Record<AskIntent, string> = {
  callers: "Who uses",
  callees: "What it uses",
  describe: "What it does",
  component_requirements: "Requirements of",
  requirement_code: "Code for",
  requirements_by_status: "Requirements by status",
  find: "Search",
  empty: "Question",
};

const PARSED_BY: Record<string, string> = {
  rules: "understood from the wording",
  llm: "understood by the local model",
  fallback: "not understood, so searched instead",
};

/** "line 12" / "lines 12, 40" (where the call happens inside the component). */
export function linesLabel(lines: number[] | undefined): string {
  if (!lines?.length) return "";
  return `${lines.length === 1 ? "line" : "lines"} ${lines.join(", ")}`;
}

function AskComponentRow({ id, c, showSummary }: { id: number; c: AskComponent; showSummary?: boolean }) {
  return (
    <div className="tl-in flex flex-col gap-1.5 border-b border-border px-4 py-3 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <Link to={codeHref(id, c.component_id)} className="min-w-0 truncate font-mono text-[13px] font-medium text-fg">{c.name}</Link>
        <span className="flex-none font-mono text-xs text-fg3">{c.path}:{c.start_line}–{c.end_line}</span>
      </div>
      {(c.relation || c.lines?.length) && (
        <div className="text-xs text-fg2">
          {c.relation}{c.relation && c.lines?.length ? " · " : ""}{linesLabel(c.lines)}
        </div>
      )}
      {showSummary && (
        c.summary
          ? <div className="text-[13px] text-fg">{c.summary}
              <span className="ml-1.5 text-xs text-fg3">{c.summary_kind === "generated" ? "(generated description, may be imprecise)" : "(from the code's docstring)"}</span>
            </div>
          : <div className="text-xs text-fg3">No description; open it to read the code.</div>
      )}
      <RequirementChips id={id} requirements={c.requirements} />
    </div>
  );
}

function AskAnswer({ id, q, data }: { id: number; q: string; data: AskResult }) {
  const describe = data.intent === "describe";
  const listTitle = data.intent === "callees" ? "Uses" : data.intent === "callers" ? "Used by" : "Code";
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Answer" className="rounded-lg border border-border bg-panel px-4 py-3.5">
        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-fg3">
          <span className="rounded-[3px] bg-hover px-1.5 font-mono text-[10px] leading-4">{INTENT_LABEL[data.intent] ?? data.intent}</span>
          {data.target && data.intent !== "find" && <span className="font-mono">{data.target}</span>}
          {data.parsed_by && <span>· {PARSED_BY[data.parsed_by] ?? data.parsed_by}</span>}
        </div>
        <div className="text-[15px] font-medium text-fg">{data.answer}</div>
        {!describe && data.matches.length > 0 && (
          <div className="mt-1.5 flex flex-wrap items-baseline gap-1.5 text-xs text-fg3">
            Matched
            {data.matches.map((m) => (
              <Link key={m.component_id} to={codeHref(id, m.component_id)} className="font-mono">{m.name}</Link>
            ))}
          </div>
        )}
        {data.note && <div className="mt-2 text-xs text-fg3">{data.note}</div>}
      </section>

      {describe && data.matches.length > 0 && (
        <section aria-labelledby="ask-match" className="rounded-lg border border-border bg-panel">
          <SectionHead id="ask-match" title="Matched code" count={`${data.matches.length} found`} />
          {data.matches.map((c) => <AskComponentRow key={c.component_id} id={id} c={c} showSummary />)}
        </section>
      )}

      {data.components.length > 0 && (
        <section aria-labelledby="ask-code" className="rounded-lg border border-border bg-panel">
          <SectionHead id="ask-code" title={listTitle} count={`${data.components.length} component${data.components.length === 1 ? "" : "s"}`} />
          {data.components.map((c) => <AskComponentRow key={c.component_id} id={id} c={c} />)}
        </section>
      )}

      {data.requirements.length > 0 && (
        <section aria-labelledby="ask-req" className="rounded-lg border border-border bg-panel">
          <SectionHead id="ask-req" title="Requirements" count={`${data.requirements.length} found`} />
          {data.requirements.map((r) => (
            <div key={r.requirement_id} className="tl-in flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2">
                <Link to={reqHref(id, r.requirement_id)} className="font-mono text-xs font-medium">{r.requirement_id}</Link>
                <Link to={reqHref(id, r.requirement_id)} className="min-w-0 flex-1 truncate text-sm font-medium text-fg">{r.title ?? ""}</Link>
                <StatusChip meta={verdictMeta(r.verdict)} />
              </div>
              <ImplementedBy id={id} components={r.components} verdict={r.verdict} />
            </div>
          ))}
        </section>
      )}

      {data.intent === "find" && data.search && <SearchResults id={id} q={q} data={data.search} />}
    </div>
  );
}

const ASK_EXAMPLES = ["which functions use can_borrow()?", "what does checkout do?", "which requirements are not implemented?", "which code implements FR-016?"];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Search() {
  const { runId } = useParams();
  const id = Number(runId);
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const ask = params.get("mode") === "ask";
  const [draft, setDraft] = useState(q);
  const input = useRef<HTMLInputElement>(null);
  const { data: results } = useResults(id);

  useEffect(() => setDraft(q), [q]);

  // The query and the mode live in the URL. A query only runs when the form is
  // submitted (Enter), not on every keystroke.
  const go = (text: string, askMode = ask) => {
    const next: Record<string, string> = {};
    if (askMode) next.mode = "ask";
    if (text.trim()) next.q = text.trim();
    setParams(next, { replace: true });
  };

  // "/" focuses the box.
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

  const search = useQuery({
    queryKey: ["search", id, q],
    queryFn: () => api.get<SearchResult>(`/api/runs/${id}/search?q=${encodeURIComponent(q)}&limit=10`),
    enabled: !!q && !ask,
    placeholderData: (prev) => prev,
  });
  const answer = useQuery({
    queryKey: ["ask", id, q],
    queryFn: () => api.get<AskResult>(`/api/runs/${id}/ask?q=${encodeURIComponent(q)}&limit=10`),
    enabled: !!q && ask,
    placeholderData: (prev) => prev,
  });
  const { isFetching, error } = ask ? answer : search;
  const data = search.data;

  const examples = ask ? ASK_EXAMPLES : (results?.requirements ?? []).slice(0, 4).map((r) => r.title).filter(Boolean) as string[];
  const noScope = !ask && data?.scope && !data.scope.requirements && !data.scope.code;

  const modeButton = (label: string, on: boolean, askMode: boolean) => (
    <button type="button" role="tab" aria-selected={on} onClick={() => { if (!on) go(draft, askMode); input.current?.focus(); }}
      className={`h-7 cursor-pointer rounded-[5px] border-0 px-2.5 text-[13px] font-medium ${on ? "bg-panel text-fg shadow-sm" : "bg-transparent text-fg3 hover:text-fg"}`}>
      {label}
    </button>
  );

  return (
    <div className="flex flex-col">
      <header className="border-b border-border bg-panel px-8 pt-5 pb-5">
        <div className="mb-0.5 text-xs text-fg3">
          <Link to={`/runs/${id}/results`} className="text-fg3">Run #{id}</Link> / Search
        </div>
        <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">Search this run</h1>
        <div className="text-[13px] text-fg3">
          {ask
            ? "Ask a question in plain words: who calls a function, what a function does, which code implements a requirement, which requirements are missing."
            : "Find a feature by keyword or sentence, then the code that implements it. Matches by wording and by meaning."}
        </div>
        <div className="mt-4 flex max-w-[860px] items-center gap-2.5">
          <div role="tablist" aria-label="Search mode" className="flex flex-none gap-0.5 rounded-md bg-hover p-0.5">
            {modeButton("Search", !ask, false)}
            {modeButton("Ask", ask, true)}
          </div>
          <form className="flex flex-1 items-center gap-2.5 rounded-lg border border-border-strong bg-panel px-3 focus-within:border-accent"
            onSubmit={(e) => { e.preventDefault(); go(draft); }}>
            <span className="text-fg3"><SearchIcon size={16} /></span>
            <input ref={input} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
              aria-label={ask ? "Ask a question about this run" : "Search requirements and code"}
              placeholder={ask ? "e.g. which functions use can_borrow()?" : "e.g. renew a loan, overdue fines, FR-016"}
              className="h-11 flex-1 border-0 bg-transparent text-[15px] text-fg outline-none placeholder:text-fg3" />
            {isFetching && <span className="h-3.5 w-3.5 rounded-full border-[1.5px] border-accent" style={{ borderRightColor: "transparent", animation: "tlSpin 800ms linear infinite" }} />}
            {draft && (
              <button type="button" aria-label="Clear search" onClick={() => { setDraft(""); go(""); input.current?.focus(); }}
                className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-fg3 hover:bg-hover hover:text-fg"><XIcon /></button>
            )}
            {draft.trim() && draft.trim() !== q
              ? <span className="text-[11px] whitespace-nowrap text-fg3">Press <kbd className="rounded-[3px] border border-b-2 border-border-strong px-[5px] font-mono text-[11px]">Enter</kbd> to {ask ? "ask" : "search"}</span>
              : <kbd className="rounded-[3px] border border-b-2 border-border-strong px-[5px] font-mono text-[11px] text-fg3">/</kbd>}
          </form>
        </div>
      </header>

      <div className="flex max-w-[1280px] flex-col gap-4 px-8 pt-6 pb-12">
        {error && <Alert tone="error" title={ask ? "Could not answer." : "Search failed."}>{(error as ApiError).message}</Alert>}
        {!q && (
          <div className="text-[13px] text-fg3">
            {examples.length > 0 ? (
              <>Try{" "}
                {examples.map((t, i) => (
                  <span key={t}>{i > 0 && ", "}
                    <button onClick={() => { setDraft(t); go(t); }} className="cursor-pointer border-0 bg-transparent p-0 text-accent">“{t}”</button>
                  </span>
                ))}
                {ask ? "." : " or a requirement ID."}</>
            ) : "Type what you are looking for: a feature, a rule, a requirement ID."}
          </div>
        )}
        {noScope && <Alert tone="info">Nothing to search yet: requirements and code are indexed as the run progresses. <Link to={`/runs/${id}/pipeline`}>Watch the pipeline →</Link></Alert>}

        {q && !ask && data && !noScope && <SearchResults id={id} q={q} data={data} />}
        {q && ask && answer.data && <AskAnswer id={id} q={q} data={answer.data} />}
      </div>
    </div>
  );
}
