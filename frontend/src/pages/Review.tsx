import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useRun } from "../api/hooks";
import type { DocBlock, MergeTarget, Resolution, ReviewItem, ReviewState } from "../api/types";
import { Button } from "../components/ui/Button";
import { Alert } from "../components/ui/Form";
import { ProgressBar } from "../components/ui/Progress";
import { plural } from "../lib/format";
import {
  CATEGORIES, displayId, itemsFor, locateBlocks, locationLabel, resolutionView, suggestionLabel, TABS, type Tab,
} from "../lib/review";

const Kbd = ({ children }: { children: string }) => (
  <kbd className="rounded-[3px] border border-b-2 border-border-strong bg-panel px-[5px] py-px font-mono text-[11px] font-medium">{children}</kbd>
);

function useReview(id: number) {
  return useQuery({ queryKey: ["review", id], queryFn: () => api.get<ReviewState>(`/api/runs/${id}/review`) });
}

function useDocument(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: () => api.get<{ type: string; blocks: DocBlock[] }>(`/api/runs/${id}/document`),
    enabled,
    staleTime: Infinity,
  });
}

// ---------------------------------------------------------------------------
// Merge picker
// ---------------------------------------------------------------------------

function MergePicker({ runId, item, requirements, onPick }: {
  runId: number;
  item: ReviewItem;
  requirements: ReviewState["requirements"];
  onPick: (target: string) => void;
}) {
  const [q, setQ] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const { data, isLoading } = useQuery({
    queryKey: ["targets", runId, item.item_key],
    queryFn: () => api.get<{ targets: MergeTarget[] }>(`/api/runs/${runId}/review/targets?item=${encodeURIComponent(item.item_key)}&limit=8`),
  });
  const query = q.trim().toLowerCase();
  const ranked = data?.targets ?? [];
  const list: { requirement_id: string; title: string; similarity?: number; suggested?: boolean }[] = query
    ? requirements
        .filter((r) => r.requirement_id && `${r.requirement_id} ${r.title}`.toLowerCase().includes(query) && r.requirement_id !== item.requirement_id)
        .slice(0, 20)
        .map((r) => ({ ...r, similarity: ranked.find((t) => t.requirement_id === r.requirement_id)?.similarity }))
    : ranked;
  return (
    <div role="listbox" aria-label="Merge target"
      className="tl-in absolute top-11 left-4 z-[3] w-[380px] rounded-lg border border-border-strong bg-panel shadow-panel"
      style={{ animationDuration: "150ms" }} onClick={(e) => e.stopPropagation()}>
      <div className="border-b border-border p-2">
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search requirements by ID or title"
          aria-label="Search merge targets"
          className="h-[30px] w-full rounded-[5px] border border-border-strong bg-panel px-2 text-[13px] text-fg outline-none focus:border-accent" />
      </div>
      <div className="max-h-[240px] overflow-y-auto p-1">
        {isLoading && !query && <div className="px-2 py-2 text-xs text-fg3">Ranking by similarity…</div>}
        {list.map((t) => (
          <button key={t.requirement_id} role="option" aria-selected={!!t.suggested} onClick={() => onPick(t.requirement_id)}
            className="grid h-[34px] w-full cursor-pointer items-center gap-2 rounded-[5px] border-0 px-2 text-left text-[13px] hover:bg-hover"
            style={{ gridTemplateColumns: "72px 1fr auto", background: t.suggested ? "var(--accent-bg)" : "transparent" }}>
            <span className="font-mono text-xs font-medium">{t.requirement_id}</span>
            <span className="truncate">{t.title}</span>
            <span className="font-mono text-[11px] text-fg3">{t.similarity != null ? t.similarity.toFixed(2) : ""}</span>
          </button>
        ))}
        {!isLoading && list.length === 0 && <div className="px-2 py-2 text-xs text-fg3">No matching requirement.</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Item card (open) and resolved row
// ---------------------------------------------------------------------------

interface CardProps {
  item: ReviewItem;
  focused: boolean;
  checked: boolean;
  editing: boolean;
  merging: boolean;
  fixing: boolean;
  idDraft?: string;
  draft: string;
  requirements: ReviewState["requirements"];
  runId: number;
  onFocus: () => void;
  onCheck: () => void;
  onResolve: (resolution: Resolution, data?: Record<string, string>) => void;
  onEdit: (on: boolean) => void;
  onDraft: (text: string) => void;
  onMerge: (on: boolean) => void;
  onFix: (on: boolean) => void;
  onIdDraft: (id: string) => void;
  readOnly: boolean;
}

const ActionButton = ({ label, k, onClick, hover, active }: { label: string; k?: string; onClick: () => void; hover?: string; active?: boolean }) => (
  <button onClick={(e) => { e.stopPropagation(); onClick(); }}
    className={`flex h-7 cursor-pointer items-center gap-2 rounded-md border bg-panel px-2.5 text-[13px] ${hover ?? "hover:border-fg3"}`}
    style={{ borderColor: active ? "var(--accent)" : "var(--border-strong)" }}>
    {label} {k && <kbd className="font-mono text-[10px] font-medium text-fg3">{k}</kbd>}
  </button>
);

function ItemCard(p: CardProps) {
  const { item } = p;
  const cat = CATEGORIES[item.category];
  const pay = item.payload;
  const suggestion = suggestionLabel(item);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (p.focused && ref.current && document.activeElement?.tagName !== "TEXTAREA" && document.activeElement?.tagName !== "INPUT") {
      ref.current.focus({ preventScroll: true });
      ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [p.focused]);
  const idData = (): Record<string, string> => (p.idDraft ? { requirement_id: p.idDraft } : {});
  const applySuggestion = () => {
    const s = pay.suggestion;
    if (!s) return;
    if (s.action === "merge" && s.target) p.onResolve("merged", { into: s.target });
    else if (s.action === "edit") p.onEdit(true);
    else if (s.action === "discard") p.onResolve("discarded");
  };
  const extra = pay.kind === "skipped_section" ? `${plural(pay.items?.length ?? 0, "item")} in this section` : null;

  return (
    <article ref={ref} tabIndex={0} onFocus={p.onFocus} onClick={p.onFocus} aria-label={`${cat.label} ${displayId(item, p.idDraft)}`}
      className="tl-in rounded-lg border bg-panel outline-none transition-[border-color,box-shadow] duration-150"
      style={{ borderColor: p.focused ? "var(--accent)" : "var(--border)", boxShadow: p.focused ? "0 0 0 3px var(--accent-bg)" : "none" }}>
      <div className="flex flex-wrap items-center gap-2.5 border-b border-border px-4 py-2.5">
        {!p.readOnly && (
          <input type="checkbox" checked={p.checked} onChange={p.onCheck} onClick={(e) => e.stopPropagation()} aria-label="Select item"
            className="m-0 h-[15px] w-[15px] accent-[var(--accent)]" />
        )}
        <span className="inline-flex h-[22px] items-center rounded px-2 text-xs font-medium" style={{ background: cat.b, color: cat.c }}>{cat.label}</span>
        {p.fixing ? (
          <input autoFocus defaultValue={displayId(item, p.idDraft)} aria-label="Requirement ID"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Enter") { p.onIdDraft((e.target as HTMLInputElement).value.trim()); p.onFix(false); }
              if (e.key === "Escape") p.onFix(false);
            }}
            onBlur={(e) => { p.onIdDraft(e.target.value.trim()); p.onFix(false); }}
            className="h-6 w-[110px] rounded border border-accent bg-panel px-1.5 font-mono text-xs font-medium text-fg outline-none" />
        ) : (
          <span className="font-mono text-[13px] font-medium">{displayId(item, p.idDraft)}</span>
        )}
        <span className="min-w-0 truncate text-sm font-medium">{pay.title}</span>
        {pay.confidence && <span className="ml-auto font-mono text-xs text-fg3">confidence {pay.confidence}</span>}
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}>
        <div className="flex flex-col gap-1.5 border-r border-border px-4 py-3">
          <div className="flex justify-between gap-2 text-xs text-fg3">
            <span>Source text</span>
            <button onClick={p.onFocus} className="cursor-pointer border-0 bg-transparent p-0 font-mono text-xs text-accent">
              {locationLabel(pay.location) || "show in document"}
            </button>
          </div>
          <div className="max-h-[220px] overflow-y-auto rounded-md bg-subtle px-3 py-2.5 text-sm leading-relaxed text-pretty whitespace-pre-line">
            {pay.source_text || <span className="text-fg3">(no text)</span>}
          </div>
          {extra && <div className="text-xs text-fg3">Keeping it extracts each item as its own requirement.</div>}
        </div>
        <div className="flex flex-col gap-1.5 px-4 py-3">
          <div className="text-xs text-fg3">{pay.kind === "requirement" ? "Extracted" : "Not extracted yet"}</div>
          <dl className="m-0 grid gap-x-3 gap-y-1 text-[13px]" style={{ gridTemplateColumns: "84px minmax(0,1fr)" }}>
            <dt className="text-fg3">Type</dt><dd className="m-0">{pay.type ?? "—"}</dd>
            <dt className="text-fg3">Subtype</dt><dd className="m-0">{pay.subtype ?? "—"}</dd>
            <dt className="text-fg3">{pay.kind === "requirement" ? "Normalized" : "Text"}</dt>
            <dd className="m-0">
              {p.editing ? (
                <>
                  <textarea autoFocus value={p.draft} onChange={(e) => p.onDraft(e.target.value)} rows={4} aria-label="Requirement text"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") p.onEdit(false);
                      if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && p.draft.trim()) p.onResolve("edited", { text: p.draft.trim(), ...idData() });
                    }}
                    className="w-full resize-y rounded-md border border-accent bg-panel px-2 py-1.5 font-sans text-[13px] leading-normal text-fg outline-none" />
                  <span className="mt-1.5 flex gap-1.5">
                    <Button size="sm" variant="primary" disabled={!p.draft.trim()}
                      onClick={(e) => { e.stopPropagation(); p.onResolve("edited", { text: p.draft.trim(), ...idData() }); }}>
                      Save and keep
                    </Button>
                    <Button size="sm" onClick={(e) => { e.stopPropagation(); p.onEdit(false); }}>Cancel</Button>
                  </span>
                </>
              ) : (
                <span className="text-pretty">{pay.normalized_text || pay.source_text || "—"}</span>
              )}
            </dd>
          </dl>
        </div>
      </div>

      <div className="flex gap-2 border-t border-border bg-subtle px-4 py-2.5 text-[13px] text-fg2">
        <span className="flex-none font-mono text-[11px] leading-5 font-medium text-fg3">WHY FLAGGED</span>
        <span className="flex flex-col gap-0.5 text-pretty">
          {pay.reasons.map((r) => <span key={r}>{r}</span>)}
        </span>
      </div>

      {!p.readOnly && (
        <div className="relative flex flex-wrap items-center gap-1.5 border-t border-border px-4 py-2.5">
          <ActionButton label="Keep" k="K" hover="hover:border-ok hover:text-ok" onClick={() => p.onResolve("kept", idData())} />
          <ActionButton label="Discard" k="D" hover="hover:border-bad hover:text-bad" onClick={() => p.onResolve("discarded")} />
          <ActionButton label="Edit text" k="E" onClick={() => p.onEdit(true)} />
          <ActionButton label="Merge into…" k="M" active={p.merging} onClick={() => p.onMerge(!p.merging)} />
          <button onClick={(e) => { e.stopPropagation(); p.onFix(true); }}
            className="h-7 cursor-pointer rounded-md border border-transparent bg-transparent px-2.5 text-[13px] text-fg2 hover:text-fg">
            Fix ID
          </button>
          {suggestion && (
            <span className="ml-auto text-xs text-fg3">
              Suggested:{" "}
              <button onClick={(e) => { e.stopPropagation(); applySuggestion(); }} className="cursor-pointer border-0 bg-transparent p-0 text-xs text-accent">
                {suggestion}
              </button>
            </span>
          )}
          {p.merging && (
            <MergePicker runId={p.runId} item={item} requirements={p.requirements}
              onPick={(into) => p.onResolve("merged", { into })} />
          )}
        </div>
      )}
    </article>
  );
}

function ResolvedRow({ item, onUndo, onFocus, readOnly }: { item: ReviewItem; onUndo: () => void; onFocus: () => void; readOnly: boolean }) {
  const r = resolutionView(item);
  return (
    <div onClick={onFocus} className="tl-in flex h-11 items-center gap-3 rounded-lg border border-border bg-panel px-4 text-[13px]">
      <span aria-hidden="true" className="h-3.5 w-3.5 flex-none rounded-full text-center text-[8px] leading-[14px] font-bold"
        style={{ background: r.c, color: "var(--panel)" }}>{r.g}</span>
      <span className="w-[84px] flex-none truncate font-mono text-xs font-medium">{displayId(item)}</span>
      <span className="min-w-0 flex-1 truncate text-fg2">{item.payload.title}</span>
      <span className="text-xs" style={{ color: r.c }}>{r.label}</span>
      {!readOnly && (
        <button onClick={(e) => { e.stopPropagation(); onUndo(); }}
          className="h-6 cursor-pointer rounded border border-border bg-panel px-2 text-xs text-fg2 hover:bg-hover">
          {item.resolution_data?.auto ? "Restore" : "Undo"}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Document preview
// ---------------------------------------------------------------------------

function DocPreview({ fileName, blocks, item }: { fileName: string; blocks: DocBlock[] | undefined; item: ReviewItem | null }) {
  const hits = useMemo(() => (blocks && item ? locateBlocks(blocks, item) : []), [blocks, item]);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!hits.length || !box.current) return;
    const el = box.current.querySelector(`[data-block="${hits[0]}"]`) as HTMLElement | null;
    if (el) box.current.scrollTo({ top: el.offsetTop - 80, behavior: "smooth" });
  }, [hits]);
  const hit = new Set(hits);
  return (
    <aside aria-label="Document preview" className="sticky top-[150px] flex h-[calc(100vh-150px)] flex-col self-start border-l border-border bg-panel">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5 text-xs">
        <span className="truncate font-mono text-fg2">{fileName}</span>
        <span className="font-mono text-fg3">{blocks ? `${blocks.length} blocks` : ""}</span>
      </div>
      <div ref={box} className="relative flex-1 overflow-y-auto bg-subtle p-5">
        {!blocks ? (
          <div className="text-xs text-fg3">Loading the document…</div>
        ) : (
          <div className="min-h-[420px] rounded-[2px] border border-border bg-panel px-6 py-7 text-xs leading-[1.7] text-fg2 shadow-[0_1px_2px_rgba(0,0,0,.04)]">
            {blocks.map((b, i) => {
              const on = hit.has(i);
              const style = { background: on ? "var(--part-bg)" : "transparent", color: on ? "var(--fg)" : undefined,
                outline: on ? "1px solid var(--part)" : "none" };
              if (b.kind === "heading") {
                return <div key={i} data-block={i} className="mx-[-6px] mt-3 mb-2 rounded-[3px] px-1.5 text-[13px] font-semibold text-fg" style={style}>{b.text}</div>;
              }
              if (b.kind === "table") {
                return (
                  <div key={i} data-block={i} className="mx-[-6px] mb-2.5 overflow-x-auto rounded-[3px] px-1.5 py-1" style={style}>
                    <table className="w-full border-collapse text-[11px]">
                      <tbody>
                        {b.rows.map((row, r) => (
                          <tr key={r}>{row.map((c, k) => <td key={k} className="border border-border px-1.5 py-0.5 align-top">{c}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              }
              return (
                <p key={i} data-block={i} className={`mx-[-6px] mt-0 mb-2.5 rounded-[3px] px-1.5 py-1 text-pretty transition-colors duration-200 ${b.kind === "list_item" ? "pl-5" : ""}`} style={style}>
                  {b.kind === "list_item" ? "• " : ""}{b.text}
                </p>
              );
            })}
          </div>
        )}
      </div>
      <div className="border-t border-border px-4 py-2 font-mono text-[11px] text-fg3">
        {item ? (hits.length ? `Showing ${locationLabel(item.payload.location) || "the source"} for ${displayId(item)}` : `Location not found in the parsed document for ${displayId(item)}`) : "Select an item to see where it comes from"}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Review() {
  const { runId } = useParams();
  const id = Number(runId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: run } = useRun(id);
  const { data: review, error, isLoading } = useReview(id);
  const { data: doc } = useDocument(id, !!review?.ready);

  const [tab, setTab] = useState<Tab | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [edit, setEdit] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [merging, setMerging] = useState<string | null>(null);
  const [fixing, setFixing] = useState<string | null>(null);
  const [ids, setIds] = useState<Record<string, string>>({});
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [toast, setToast] = useState<{ text: string; keys: string[] } | null>(null);
  const [problem, setProblem] = useState<{ text: string; keys: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const items = review?.items ?? [];
  const counts = review?.counts;
  // Open on the first tab with open items, else "All requirements".
  const activeTab: Tab = tab ?? (TABS.find((t) => t !== "all" && items.some((i) => i.category === t && !i.resolution)) ?? "all");
  const visible = itemsFor(items, activeTab);
  const pending = visible.filter((i) => !i.resolution);
  const readOnly = review?.status === "done" || run?.status === "cancelled";
  const focusItem = items.find((i) => i.item_key === focus) ?? pending[0] ?? visible[0] ?? null;

  const refresh = useCallback(async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["review", id] }),
      qc.invalidateQueries({ queryKey: keys.run(id) }),
      qc.invalidateQueries({ queryKey: keys.runs }),
    ]);
  }, [qc, id]);

  const showToast = (text: string, undoKeys: string[]) => {
    clearTimeout(toastTimer.current);
    setToast({ text, keys: undoKeys });
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  };

  const call = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await fn();
      await refresh();
      return true;
    } catch (e) {
      const err = e as ApiError;
      setProblem({ text: err.message, keys: err.keys ?? [] });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (item: ReviewItem, resolution: Resolution, data: Record<string, string> = {}) => {
    const next = pending.find((i) => i.item_key !== item.item_key && pending.indexOf(i) > pending.indexOf(item)) ?? pending.find((i) => i.item_key !== item.item_key);
    const ok = await call(() => api.json("PUT", `/api/runs/${id}/review/items/${encodeURIComponent(item.item_key)}`, { resolution, data }));
    if (!ok) return;
    setEdit(null);
    setMerging(null);
    setFocus(next?.item_key ?? null);
    const label = resolution === "discarded" ? "Discarded" : resolution === "merged" ? "Merged" : "Kept";
    showToast(`${label} ${displayId(item, ids[item.item_key])}${resolution === "merged" ? ` into ${data.into}` : ""}`, [item.item_key]);
  };

  const undo = async (undoKeys: string[]) => {
    setToast(null);
    await call(() => Promise.all(undoKeys.map((k) => api.json("DELETE", `/api/runs/${id}/review/items/${encodeURIComponent(k)}`))));
    if (undoKeys.length === 1) setFocus(undoKeys[0]);
  };

  const selected = Object.keys(sel).filter((k) => sel[k] && items.some((i) => i.item_key === k && !i.resolution));
  const bulk = async (resolution: "kept" | "discarded") => {
    const ok = await call(() => api.json("POST", `/api/runs/${id}/review/bulk`, { keys: selected, resolution }));
    if (ok) {
      showToast(`${resolution === "kept" ? "Kept" : "Discarded"} ${plural(selected.length, "item")}`, selected);
      setSel({});
    }
  };

  const complete = async () => {
    const ok = await call(() => api.json("POST", `/api/runs/${id}/review/complete`));
    if (ok) navigate(`/runs/${id}/pipeline`);
  };

  // Keyboard: ↑↓ move between open items; K D E M act on the focused one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || readOnly || e.ctrlKey || e.metaKey || e.altKey) return;
      const idx = pending.findIndex((i) => i.item_key === focusItem?.item_key);
      const k = e.key.toLowerCase();
      if (k === "arrowdown" || k === "arrowup") {
        e.preventDefault();
        const n = pending[Math.max(0, Math.min(pending.length - 1, idx + (k === "arrowdown" ? 1 : -1)))];
        if (n) setFocus(n.item_key);
        return;
      }
      if (!focusItem || focusItem.resolution) return;
      if (k === "escape") { setMerging(null); setEdit(null); return; }
      if (!["k", "d", "e", "m"].includes(k)) return;
      e.preventDefault();          // the shortcut must not also type into the field it opens
      if (k === "k") resolve(focusItem, "kept", ids[focusItem.item_key] ? { requirement_id: ids[focusItem.item_key] } : {});
      else if (k === "d") resolve(focusItem, "discarded");
      else if (k === "e") setEdit(focusItem.item_key);
      else setMerging(focusItem.item_key);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  if (isLoading) return <div className="px-8 py-6 text-[13px] text-fg3">Loading review…</div>;
  if (error || !review) {
    return <div className="px-8 py-6"><Alert tone="error" title="Could not load the review.">{(error as ApiError)?.message}</Alert></div>;
  }

  const header = (
    <div className="mb-0.5 text-xs text-fg3">
      <Link to={`/runs/${id}/pipeline`} className="text-fg3">Run #{id}</Link> / Review
    </div>
  );

  if (!review.ready) {
    return (
      <div>
        <header className="border-b border-border bg-panel px-8 py-5">
          {header}
          <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">Review extracted requirements</h1>
        </header>
        <div className="px-8 py-6">
          <Alert tone="info">
            The SRS Agent is still extracting requirements. The review opens as soon as it finishes (the code lane can keep running).{" "}
            <Link to={`/runs/${id}/pipeline`}>Watch the pipeline →</Link>
          </Alert>
        </div>
      </div>
    );
  }

  const open = counts?.open ?? 0;
  const flaggedKeys = new Set(items.filter((i) => i.payload.kind === "requirement").map((i) => i.payload.index));
  const others = review.requirements.filter((r) => !flaggedKeys.has(r.index));
  const unreviewedCount = items.filter((i) => i.resolution === "unreviewed").length;
  const droppedCount = items.filter((i) => i.payload.kind === "requirement" && (i.resolution === "discarded" || i.resolution === "merged")).length;
  const addedCount = items.filter((i) => i.payload.kind !== "requirement" && (i.resolution === "kept" || i.resolution === "edited" || i.resolution === "unreviewed")).length;
  const traced = review.requirements.length - droppedCount + addedCount;
  const canContinue = open === 0 && !readOnly && !busy;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-[2] border-b border-border bg-panel">
        <div className="flex flex-wrap items-end justify-between gap-6 px-8 pt-5 pb-4">
          <div>
            {header}
            <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">Review extracted requirements before tracing</h1>
            <div className="text-[13px] text-fg3">
              {readOnly ? "The review is complete." : "The run is paused. Only flagged items block tracing; everything else was extracted with high confidence."}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="w-[180px]">
              <div className="mb-1.5 text-[13px]">
                <span className="font-mono font-medium">{counts?.resolved ?? 0}</span> of <span className="font-mono">{counts?.total ?? 0}</span> reviewed
              </div>
              <ProgressBar value={counts?.total ? counts.resolved / counts.total : 1} height={4} color={open ? "var(--accent)" : "var(--ok)"} label="Review progress" />
            </div>
            {!readOnly && (
              <Button disabled={!open || busy} onClick={() => call(() => api.json("POST", `/api/runs/${id}/review/skip-remaining`))} className="text-fg2">
                Skip remaining (mark as unreviewed)
              </Button>
            )}
            {readOnly ? (
              <Button variant="primary" onClick={() => navigate(`/runs/${id}/pipeline`)}>Open pipeline →</Button>
            ) : (
              <Button variant={canContinue ? "primary" : "secondary"} disabled={!canContinue} onClick={complete}
                title={open ? `Resolve ${plural(open, "open item")}, or skip them` : "Start search, mapping and verification"}>
                Continue tracing →
              </Button>
            )}
          </div>
        </div>
        <div role="tablist" className="flex gap-1 overflow-x-auto px-8">
          {TABS.map((t) => {
            const n = t === "all" ? review.requirements.length : counts?.open_by_category[t] ?? 0;
            const on = t === activeTab;
            return (
              <button key={t} role="tab" aria-selected={on} onClick={() => { setTab(t); setFocus(null); }}
                className="flex h-10 cursor-pointer items-center gap-1.5 border-0 bg-transparent px-2.5 text-[13px] font-medium whitespace-nowrap"
                style={{ borderBottom: `2px solid ${on ? "var(--fg)" : "transparent"}`, color: on ? "var(--fg)" : "var(--fg2)" }}>
                {t === "all" ? "All requirements" : CATEGORIES[t].tab}
                <span className="rounded-[9px] px-1.5 font-mono text-[11px] leading-[18px] font-medium"
                  style={{ background: t !== "all" && n ? "var(--rev-bg)" : "var(--hover)", color: t !== "all" && n ? "var(--rev)" : "var(--fg3)" }}>
                  {n}
                </span>
              </button>
            );
          })}
        </div>
      </header>

      <div className="grid flex-1" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(300px,380px)" }}>
        <div className="flex min-w-0 flex-col gap-3 pt-5 pr-6 pb-24 pl-8">
          {problem && (
            <Alert tone="error" title="Can’t do that yet.">
              {problem.text}
              {problem.keys.length > 0 && (
                <> {" "}
                  {problem.keys.slice(0, 6).map((k) => (
                    <button key={k} onClick={() => { setTab("all"); setFocus(k); }} className="mr-1.5 cursor-pointer border-0 bg-transparent p-0 font-mono text-xs text-accent">{k}</button>
                  ))}
                </>
              )}
            </Alert>
          )}
          {open === 0 && !readOnly && (
            <div role="status" className="tl-in flex items-center gap-3 rounded-lg border border-ok bg-ok-bg px-4 py-3.5">
              <span aria-hidden="true" className="h-[18px] w-[18px] flex-none rounded-full bg-ok text-center text-[10px] leading-[18px] font-bold text-panel">✓</span>
              <div className="flex-1">
                <div className="font-semibold">{counts?.total ? "All blocking items resolved" : "Nothing needs a decision"}</div>
                <div className="text-[13px] text-fg2">
                  {plural(traced, "requirement")} will be traced.{" "}
                  {unreviewedCount ? `${unreviewedCount} kept as unreviewed and marked in the results.` : "You can still check the list below before continuing."}
                </div>
              </div>
              <Button variant="primary" onClick={complete} disabled={busy}>Continue tracing →</Button>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-fg3">
            <span>
              {activeTab === "all"
                ? "Flagged items first, then requirements extracted with high confidence."
                : `${CATEGORIES[activeTab].label} · ${pending.length} open`}
            </span>
            {!readOnly && (
              <span className="flex items-center gap-2.5">
                <span><Kbd>↑</Kbd> <Kbd>↓</Kbd> move</span>
                <span><Kbd>K</Kbd> <Kbd>D</Kbd> <Kbd>E</Kbd> <Kbd>M</Kbd> act</span>
              </span>
            )}
          </div>

          {visible.map((item) =>
            item.resolution ? (
              <ResolvedRow key={item.item_key} item={item} readOnly={readOnly} onFocus={() => setFocus(item.item_key)} onUndo={() => undo([item.item_key])} />
            ) : (
              <ItemCard
                key={item.item_key} item={item} runId={id} requirements={review.requirements} readOnly={readOnly}
                focused={focusItem?.item_key === item.item_key} checked={!!sel[item.item_key]}
                editing={edit === item.item_key} merging={merging === item.item_key} fixing={fixing === item.item_key}
                idDraft={ids[item.item_key]}
                draft={drafts[item.item_key] ?? (item.payload.normalized_text || item.payload.source_text)}
                onFocus={() => setFocus(item.item_key)}
                onCheck={() => setSel((s) => ({ ...s, [item.item_key]: !s[item.item_key] }))}
                onResolve={(r, d) => resolve(item, r, d)}
                onEdit={(on) => { setEdit(on ? item.item_key : null); setFocus(item.item_key); }}
                onDraft={(t) => setDrafts((d) => ({ ...d, [item.item_key]: t }))}
                onMerge={(on) => { setMerging(on ? item.item_key : null); setFocus(item.item_key); }}
                onFix={(on) => setFixing(on ? item.item_key : null)}
                onIdDraft={(v) => setIds((m) => ({ ...m, [item.item_key]: v }))}
              />
            ),
          )}

          {activeTab === "all" && others.length > 0 && (
            <>
              <div className="mt-2 text-xs font-medium text-fg3">Extracted with high confidence · not blocking</div>
              <div className="rounded-lg border border-border bg-panel">
                {others.map((o) => (
                  <div key={o.index} className="grid h-9 items-center gap-3 border-b border-border px-4 text-[13px] last:border-b-0"
                    style={{ gridTemplateColumns: "84px minmax(0,1fr) 120px 140px" }}>
                    <span className="font-mono text-xs font-medium">{o.requirement_id}</span>
                    <span className="truncate">{o.title}</span>
                    <span className="text-xs text-fg3">{o.type}</span>
                    <span className="truncate text-right font-mono text-xs text-fg3">{locationLabel(o.location)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
          {activeTab !== "all" && visible.length === 0 && (
            <div className="rounded-lg border border-dashed border-border-strong px-4 py-10 text-center text-[13px] text-fg3">
              Nothing in this category. Check the other tabs, or continue tracing.
            </div>
          )}
        </div>

        <DocPreview fileName={run?.srs_filename ?? "SRS"} blocks={doc?.blocks} item={focusItem} />
      </div>

      {selected.length > 0 && !readOnly && (
        <div role="toolbar" aria-label="Bulk actions"
          className="tl-in fixed bottom-6 left-1/2 z-[5] flex -translate-x-1/2 items-center gap-2 rounded-lg bg-fg py-2 pr-2 pl-4 text-[13px] text-bg shadow-panel">
          <span className="font-mono">{selected.length}</span> selected
          {(["kept", "discarded"] as const).map((r) => (
            <button key={r} onClick={() => bulk(r)} disabled={busy}
              className="h-7 cursor-pointer rounded-[5px] border border-[rgba(127,127,127,.4)] bg-transparent px-2.5 text-bg">
              {r === "kept" ? "Keep all" : "Discard all"}
            </button>
          ))}
          <button onClick={() => setSel({})} className="h-7 cursor-pointer rounded-[5px] border-0 bg-transparent px-2.5 text-bg opacity-75">Clear</button>
        </div>
      )}

      {toast && (
        <div role="status" className="tl-in fixed right-6 bottom-6 z-[5] flex items-center gap-3 rounded-lg bg-fg py-2.5 pr-3 pl-4 text-[13px] text-bg shadow-panel">
          {toast.text}
          <button onClick={() => undo(toast.keys)}
            className="h-[26px] cursor-pointer rounded-[5px] border border-[rgba(127,127,127,.4)] bg-transparent px-2.5 font-medium text-bg">
            Undo
          </button>
        </div>
      )}
    </div>
  );
}
