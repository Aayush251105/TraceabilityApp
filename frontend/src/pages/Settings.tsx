import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useSettings } from "../api/hooks";
import type { AppSettings, Health } from "../api/types";
import { PageHeader } from "../components/layout/AppShell";
import { Button } from "../components/ui/Button";
import { fileSize } from "../components/ui/DropZone";
import { Alert, TextInput } from "../components/ui/Form";
import { XIcon } from "../components/ui/Icon";

type Role = keyof AppSettings["models"];
const ROLES: { role: Role; task: string; note: string }[] = [
  { role: "docagent", task: "Docstring generation", note: "Reader, Searcher, Writer, Verifier" },
  { role: "srs", task: "Requirement extraction", note: "Structured fields for each requirement" },
  { role: "judge", task: "Ambiguity judge", note: "Reviews uncertain candidates" },
  { role: "verifier", task: "Verification", note: "Claims and line citations" },
];

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

function Chip({ tone, label, square }: { tone: "ok" | "part" | "bad" | "nf"; label: string; square?: boolean }) {
  return (
    <span className="inline-flex h-6 items-center gap-1.5 rounded pr-2.5 pl-2 text-xs font-medium" style={{ background: `var(--${tone}-bg)`, color: `var(--${tone})` }}>
      <span className="h-2 w-2" style={{ borderRadius: square ? 2 : "50%", background: `var(--${tone})` }} />{label}
    </span>
  );
}

function Card({ id, title, subtitle, aside, children }: { id: string; title: string; subtitle: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="rounded-lg border border-border bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5">
        <div>
          <h2 id={id} className="m-0 text-sm font-semibold">{title}</h2>
          <div className="text-xs text-fg3">{subtitle}</div>
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

function NumberField({ label, hint, value, onChange, min, max, step = 1 }: {
  label: string; hint: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-[13px]">
      <span className="font-medium">{label}</span>
      <span className="text-xs text-fg3">{hint}</span>
      <TextInput type="number" mono value={value} min={min} max={max} step={step} className="w-[120px]"
        onChange={(e) => { const v = Number(e.target.value); if (!Number.isNaN(v)) onChange(Math.min(max, Math.max(min, v))); }} />
    </label>
  );
}

export function Settings() {
  const qc = useQueryClient();
  const { data, error } = useSettings();
  const saved = data?.settings;
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [host, setHost] = useState("");
  const [testHost, setTestHost] = useState<string | null>(null);
  const [newPattern, setNewPattern] = useState("");
  const [toast, setToast] = useState<{ text: string; undo?: () => void } | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    if (saved && !draft) {
      setDraft(clone(saved));
      setHost(saved.ollama_host);
    }
  }, [saved, draft]);

  // Health of the endpoint being edited (the saved one until "Test connection").
  const { data: health, isFetching: testing, refetch } = useQuery({
    queryKey: ["health", testHost ?? "saved"],
    queryFn: () => api.get<Health>(testHost ? `/api/health?host=${encodeURIComponent(testHost)}` : "/api/health"),
  });

  const notify = (text: string, undo?: () => void) => {
    clearTimeout(timer.current);
    setToast({ text, undo });
    timer.current = setTimeout(() => setToast(null), 5000);
  };
  useEffect(() => () => clearTimeout(timer.current), []);

  if (error) return <div className="px-8 py-6"><Alert tone="error" title="Could not load settings.">{(error as ApiError).message}</Alert></div>;
  if (!draft || !saved) return <div className="px-8 py-6 text-[13px] text-fg3">Loading settings…</div>;

  const set = (fn: (s: AppSettings) => void) => setDraft((d) => { const n = clone(d!); fn(n); return n; });
  const current = { ...draft, ollama_host: host.trim() };
  const dirty = JSON.stringify(current) !== JSON.stringify(saved);
  const ollama = health?.ollama;
  const pulled = ollama?.models ?? [];
  const sizes = Object.fromEntries((ollama?.details ?? []).map((m) => [m.name, m.size]));
  const sizeOf = (name: string) => sizes[name] ?? sizes[`${name}:latest`] ?? null;
  const isPulled = (name: string) => pulled.includes(name) || (!name.includes(":") && pulled.includes(`${name}:latest`));
  const missing = ollama?.ok ? ROLES.filter(({ role }) => !isPulled(draft.models[role])).length : 0;
  const db = health?.database;

  const test = () => {
    const h = host.trim();
    if (h === (testHost ?? saved.ollama_host)) refetch();
    else setTestHost(h);
  };

  const save = async () => {
    setSaving(true);
    setProblem(null);
    try {
      const res = await api.json<{ settings: AppSettings }>("PUT", "/api/settings", current);
      qc.setQueryData(["settings"], (old: { settings: AppSettings; defaults: AppSettings } | undefined) => old && { ...old, settings: res.settings });
      setDraft(clone(res.settings));
      setTestHost(null);
      await qc.invalidateQueries({ queryKey: keys.health });
      notify("Settings saved. New runs use them; running runs keep theirs.");
    } catch (e) {
      setProblem((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  };

  const removePattern = (p: string) => {
    const before = draft.source.exclude_dirs;
    set((s) => { s.source.exclude_dirs = s.source.exclude_dirs.filter((x) => x !== p); });
    notify(`Removed ${p}`, () => set((s) => { s.source.exclude_dirs = before; }));
  };

  return (
    <div>
      <PageHeader title="Settings" subtitle="Defaults for new runs on this machine. Running runs keep the settings they started with." />
      <div className="flex max-w-[880px] flex-col gap-6 px-8 pt-6 pb-12">
        {problem && <Alert tone="error" title="Not saved.">{problem}</Alert>}

        {/* Local models */}
        <Card id="ol-h" title="Local models" subtitle="Served by Ollama. Nothing is sent to external APIs."
          aside={!health ? <Chip tone="nf" label="Checking…" /> : !ollama?.ok ? <Chip tone="bad" label="Unreachable" square />
            : missing ? <Chip tone="part" label={`Connected · ${missing} model${missing > 1 ? "s" : ""} missing`} square />
              : <Chip tone="ok" label={`Connected${ollama.version ? ` · v${ollama.version}` : ""}`} />}>
          <div className="flex flex-col gap-4 p-4">
            <div className="grid items-end gap-2" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
              <label className="flex flex-col gap-1.5 text-xs font-medium text-fg2">
                Ollama endpoint
                <TextInput mono value={host} onChange={(e) => setHost(e.target.value)} invalid={!!health && !ollama?.ok} spellCheck={false} />
              </label>
              <Button onClick={test} disabled={testing}>
                {testing && <span className="h-3 w-3 rounded-full border-[1.5px] border-accent" style={{ borderRightColor: "transparent", animation: "tlSpin 800ms linear infinite" }} />}
                {testing ? "Testing…" : "Test connection"}
              </Button>
            </div>
            {health && !ollama?.ok && (
              <Alert tone="error" boxed title={`Can’t reach Ollama at ${health.ollama_host.replace(/^https?:\/\//, "")}.`}>
                Start it with <code className="rounded-[3px] bg-panel px-1 font-mono">ollama serve</code>, then test again. New runs can’t start until it’s reachable.
              </Alert>
            )}
            <div className="rounded-md border border-border">
              <div className="grid h-8 items-center gap-3 border-b border-border px-3 text-xs font-medium text-fg3"
                style={{ gridTemplateColumns: "minmax(160px,1fr) minmax(200px,1.2fr) 80px 170px" }}>
                <span>Task</span><span>Model</span><span>Size</span><span>Status</span>
              </div>
              {ROLES.map(({ role, task, note }) => {
                const name = draft.models[role];
                const ready = ollama?.ok ? isPulled(name) : null;
                const options = Array.from(new Set([name, ...pulled])).sort();
                const size = sizeOf(name);
                return (
                  <div key={role} className="grid items-center gap-3 border-b border-border px-3 py-2 text-[13px] last:border-b-0"
                    style={{ gridTemplateColumns: "minmax(160px,1fr) minmax(200px,1.2fr) 80px 170px" }}>
                    <span><span className="block font-medium">{task}</span><span className="text-xs text-fg3">{note}</span></span>
                    <select value={name} onChange={(e) => set((s) => { s.models[role] = e.target.value; })} aria-label={`${task} model`}
                      className="h-8 cursor-pointer rounded-md border border-border-strong bg-panel px-2 font-mono text-[13px] text-fg">
                      {options.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                    <span className="font-mono text-xs text-fg2">{size ? fileSize(size) : "—"}</span>
                    <span className="flex flex-col gap-0.5">
                      <span className="inline-flex items-center gap-1.5 text-xs font-medium"
                        style={{ color: ready === null ? "var(--fg3)" : ready ? "var(--ok)" : "var(--part)" }}>
                        <span className="h-2 w-2" style={{ borderRadius: ready ? "50%" : 2, background: "currentColor" }} />
                        {ready === null ? "Unknown" : ready ? "Ready" : "Not pulled"}
                      </span>
                      {ready === false && <code className="font-mono text-[11px] text-fg2">ollama pull {name}</code>}
                    </span>
                  </div>
                );
              })}
              {health?.embeddings && (
                <div className="grid items-center gap-3 px-3 py-2 text-[13px]" style={{ gridTemplateColumns: "minmax(160px,1fr) minmax(200px,1.2fr) 80px 170px" }}>
                  <span><span className="block font-medium">Embeddings</span><span className="text-xs text-fg3">Search index · runs in the app, not Ollama</span></span>
                  <span className="truncate font-mono text-[13px] text-fg2" title={health.embeddings.model}>{health.embeddings.model.split("/").pop()}</span>
                  <span className="font-mono text-xs text-fg2">{health.embeddings.dim ? `${health.embeddings.dim} dims` : "—"}</span>
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ok"><span className="h-2 w-2 rounded-full bg-ok" />Local</span>
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* Pipeline */}
        <Card id="pl-h" title="Pipeline" subtitle="How runs ingest, search, map and verify. Change these when comparing models or datasets.">
          <div className="grid gap-x-8 gap-y-5 p-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))" }}>
            <div className="flex flex-col gap-2 text-[13px]">
              <span className="font-medium">Ingestion lanes</span>
              {[{ v: true, t: "Code and SRS in parallel", d: "Fastest when the GPU holds both models." },
                { v: false, t: "SRS first, then code", d: "Better on a small GPU; the review opens sooner." }].map((o) => (
                <label key={String(o.v)} className="flex cursor-pointer items-start gap-2">
                  <input type="radio" name="lanes" checked={draft.ingest.parallel === o.v} onChange={() => set((s) => { s.ingest.parallel = o.v; })} className="mt-1 accent-[var(--accent)]" />
                  <span><span className="block">{o.t}</span><span className="text-xs text-fg3">{o.d}</span></span>
                </label>
              ))}
            </div>
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="font-medium">Claim splitting</span>
              <span className="text-xs text-fg3">How the verifier breaks a requirement into claims.</span>
              <select value={draft.verification.claims} onChange={(e) => set((s) => { s.verification.claims = e.target.value; })}
                className="h-8 w-full max-w-[320px] rounded-md border border-border-strong bg-panel px-2 text-[13px] text-fg">
                <option value="clauses">Sentences, compound ones split (default)</option>
                <option value="rules">Sentences and list items only</option>
                <option value="llm">Model splits freely (not recommended)</option>
              </select>
            </label>
            <NumberField label="Search candidates" hint="Code candidates kept per requirement." min={1} max={50}
              value={draft.search.top_n} onChange={(v) => set((s) => { s.search.top_n = v; })} />
            <NumberField label="Direct links" hint="Highest search rank that can become a direct link." min={1} max={10}
              value={draft.mapping.max_direct_rank} onChange={(v) => set((s) => { s.mapping.max_direct_rank = v; })} />
            <NumberField label="Supporting links" hint="Most supporting components per requirement." min={0} max={20}
              value={draft.mapping.max_supporting} onChange={(v) => set((s) => { s.mapping.max_supporting = v; })} />
            <NumberField label="Duplicate threshold" hint="Similarity at which review flags two requirements." min={0.5} max={1} step={0.01}
              value={draft.review.duplicate_threshold} onChange={(v) => set((s) => { s.review.duplicate_threshold = v; })} />
            <NumberField label="Upload limit (MB)" hint="Largest SRS or ZIP accepted." min={1} max={2000}
              value={draft.limits.max_upload_mb} onChange={(v) => set((s) => { s.limits.max_upload_mb = v; })} />
            <NumberField label="Large repository warning" hint="Python files above which New run warns." min={10} max={100000}
              value={draft.limits.large_repo_files} onChange={(v) => set((s) => { s.limits.large_repo_files = v; })} />
          </div>
        </Card>

        {/* Database */}
        <Card id="db-h" title="Database" subtitle="Stores runs, code graph, embeddings and verdict history."
          aside={!health ? <Chip tone="nf" label="Checking…" /> : db?.ok ? <Chip tone="ok" label="Connected" /> : <Chip tone="bad" label="Unreachable" square />}>
          {db?.ok ? (
            <dl className="m-0 grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
              <div className="border-r border-border px-4 py-3"><dt className="text-xs text-fg3">Connection</dt><dd className="m-0 truncate font-mono text-[13px]" title={db.connection}>{db.connection}</dd></div>
              <div className="border-r border-border px-4 py-3"><dt className="text-xs text-fg3">Vector extension</dt><dd className="m-0 font-mono text-[13px]">{db.pgvector ? `pgvector ${db.pgvector}` : "not installed"}</dd></div>
              <div className="px-4 py-3"><dt className="text-xs text-fg3">Size · latency</dt><dd className="m-0 font-mono text-[13px]">{db.bytes != null ? fileSize(db.bytes) : "—"} · {db.latency_ms} ms</dd></div>
            </dl>
          ) : health && (
            <div className="p-4"><Alert tone="error">{db?.error ?? "No connection."} Check the TRACEABILITY_PG_* environment variables and restart the server.</Alert></div>
          )}
        </Card>

        {/* Agents */}
        {health && (
          <Card id="ag-h" title="Agents" subtitle="Found next to the app, each in its own virtual environment."
            aside={Object.values(health.agents).every((a) => a.dir_ok && a.python_ok) ? <Chip tone="ok" label="Found" /> : <Chip tone="bad" label="Missing" square />}>
            <div>
              {Object.entries(health.agents).map(([name, a]) => (
                <div key={name} className="grid items-center gap-3 border-b border-border px-4 py-2.5 text-[13px] last:border-b-0" style={{ gridTemplateColumns: "120px minmax(0,1fr) 140px" }}>
                  <span className="font-medium">{name === "docagent" ? "DocAgent" : "SRS Agent"}</span>
                  <span className="truncate font-mono text-xs text-fg2" title={a.dir}>{a.dir}</span>
                  <span className="text-xs" style={{ color: a.dir_ok && a.python_ok ? "var(--ok)" : "var(--bad)" }}>
                    {!a.dir_ok ? "Folder not found" : !a.python_ok ? ".venv missing" : "Ready"}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Exclusions */}
        <Card id="ex-h" title="Default exclusions" subtitle="Folder names skipped anywhere in a codebase. Applied to new runs.">
          <div className="flex flex-col gap-3 p-4">
            <div className="flex flex-wrap gap-1.5">
              {draft.source.exclude_dirs.map((p) => (
                <span key={p} className="inline-flex h-7 items-center gap-1.5 rounded border border-border-strong pr-1.5 pl-2.5 font-mono text-xs">
                  {p}
                  <button onClick={() => removePattern(p)} aria-label={`Remove ${p}`} className="flex cursor-pointer border-0 bg-transparent px-0.5 text-fg3 hover:text-fg"><XIcon /></button>
                </span>
              ))}
            </div>
            <form className="flex max-w-[420px] gap-2" onSubmit={(e) => {
              e.preventDefault();
              const p = newPattern.trim().replace(/[\\/]+$/, "");
              if (p && !draft.source.exclude_dirs.includes(p)) set((s) => { s.source.exclude_dirs = [...s.source.exclude_dirs, p]; });
              setNewPattern("");
            }}>
              <TextInput mono value={newPattern} onChange={(e) => setNewPattern(e.target.value)} placeholder="e.g. migrations" aria-label="New exclusion" className="h-8 flex-1" />
              <Button type="submit">Add</Button>
            </form>
          </div>
        </Card>

        <div className="flex items-center justify-end gap-2">
          {dirty && <span className="mr-auto text-xs text-fg3">Unsaved changes</span>}
          <Button disabled={!dirty || saving} onClick={() => { setDraft(clone(saved)); setHost(saved.ollama_host); setTestHost(null); }}>Discard changes</Button>
          <Button variant="primary" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save settings"}</Button>
        </div>
      </div>

      {toast && (
        <div role="status" className="tl-in fixed right-6 bottom-6 z-[5] flex items-center gap-3 rounded-lg bg-fg py-2.5 pr-3 pl-4 text-[13px] text-bg shadow-panel">
          {toast.text}
          {toast.undo && (
            <button onClick={() => { toast.undo!(); setToast(null); }}
              className="h-[26px] cursor-pointer rounded-[5px] border border-[rgba(127,127,127,.4)] bg-transparent px-2.5 text-bg">Undo</button>
          )}
        </div>
      )}
    </div>
  );
}
