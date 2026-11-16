import type { ReviewItem, RunCard } from "../api/types";

export function makeRun(id: number, status: RunCard["status"], extra: Partial<RunCard> = {}): RunCard {
  return {
    run_id: id,
    name: `codebase · SRS ${id}`,
    status,
    error: null,
    source: { kind: "folder", ref: "C:\\work\\library_system", git_ref: null, commit_sha: null },
    srs_filename: "SRS_v1.1.docx",
    document_id: null,
    repo_id: null,
    created_at: "2026-10-31T09:00:00Z",
    started_at: "2026-10-31T09:00:00Z",
    finished_at: null,
    summary: {},
    models: null,
    progress: { fraction: 0, remaining_seconds: null },
    rail: [],
    review: { total: 0, resolved: 0, open: 0, open_by_category: {} },
    ...extra,
  };
}

/** Replace fetch with a router: {"GET /api/runs": body | (init) => body}. Unknown routes → 404. */
export function mockFetch(routes: Record<string, unknown | ((init?: RequestInit) => unknown)>) {
  const calls: { method: string; url: string; init?: RequestInit }[] = [];
  const fn = async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ method, url, init });
    const key = `${method} ${url.split("?")[0]}`;
    if (!(key in routes)) return new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 });
    const value = routes[key];
    const body = typeof value === "function" ? (value as (i?: RequestInit) => unknown)(init) : value;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200 });
  };
  return { fn, calls };
}

/** A review item with defaults (a flagged requirement). */
export function item(key: string, extra: Partial<ReviewItem> = {}, payload: Partial<ReviewItem["payload"]> = {}): ReviewItem {
  return {
    run_id: 4, item_key: key, position: 0, category: "flagged", requirement_id: null, resolution: null,
    resolution_data: {}, resolved_at: null, ...extra,
    payload: { kind: "requirement", title: "T", source_text: "", normalized_text: "", location: {}, reasons: ["r"], ...payload },
  };
}
