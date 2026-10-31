import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { keys, useHealth, useSettings } from "../api/hooks";
import type { AppSettings, InspectResult, RunCard } from "../api/types";
import { Alert, Field, Panel, Segmented, TextInput } from "../components/ui/Form";
import { DropZone, FileBadge, fileSize } from "../components/ui/DropZone";
import { XIcon } from "../components/ui/Icon";
import { approx } from "../lib/format";

/** Typical timings on a local model (DocAgent ~40 s per component; verifier measured at ~20 s per requirement). */
export const SECONDS_PER_COMPONENT = 40;
export const SECONDS_PER_REQUIREMENT = 20;
const SRS_EXT = [".docx", ".pdf", ".md", ".txt"];
const GIT_URL = /^https:\/\/[A-Za-z0-9.-]+(:\d+)?\/[A-Za-z0-9._~/-]+$/;

type SrsMode = "upload" | "paste";
type CodeMode = "zip" | "folder" | "git";
type Inspect = { state: "idle" | "loading" | "done" | "error"; result?: InspectResult; error?: string };

const ROLES: { role: keyof AppSettings["models"]; label: string }[] = [
  { role: "docagent", label: "Docstring generation" },
  { role: "srs", label: "Requirement extraction" },
  { role: "judge", label: "Candidate judge" },
  { role: "verifier", label: "Verification" },
];

function srsProblem(file: File, maxMb: number): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!SRS_EXT.includes(ext)) return `${file.name} is not a supported format. Use ${SRS_EXT.join(", ")}.`;
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > maxMb * 1024 * 1024) return `${file.name} is larger than ${maxMb} MB.`;
  return null;
}

/** Run an inspection request, ignoring answers to requests that were superseded. */
function useInspect() {
  const [inspect, setInspect] = useState<Inspect>({ state: "idle" });
  const seq = useRef(0);
  const run = (form: FormData | null) => {
    const id = ++seq.current;
    if (!form) {
      setInspect({ state: "idle" });
      return;
    }
    setInspect({ state: "loading" });
    api
      .form<InspectResult>("/api/inspect", form)
      .then((result) => id === seq.current && setInspect({ state: "done", result }))
      .catch((e: ApiError) => id === seq.current && setInspect({ state: "error", error: e.message }));
  };
  return [inspect, run] as const;
}

function Stat({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return (
    <div className={`px-3 py-2.5 ${last ? "" : "border-r border-border"}`}>
      <div className="text-xs text-fg3">{label}</div>
      <div className="font-mono text-sm font-medium">{value}</div>
    </div>
  );
}

export function NewRun() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: settingsData } = useSettings();
  const { data: health } = useHealth();
  const settings = settingsData?.settings;
  const maxMb = settings?.limits.max_upload_mb ?? 200;

  // SRS
  const [srsMode, setSrsMode] = useState<SrsMode>("upload");
  const [srsFile, setSrsFile] = useState<File | null>(null);
  const [srsError, setSrsError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");

  // Code
  const [codeMode, setCodeMode] = useState<CodeMode>("git");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [folder, setFolder] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [gitRef, setGitRef] = useState("");
  const [inspect, runInspect] = useInspect();

  // Advanced
  const [advOpen, setAdvOpen] = useState(false);
  const [models, setModels] = useState<AppSettings["models"] | null>(null);
  const [exclude, setExclude] = useState<string[] | null>(null);
  const [newPattern, setNewPattern] = useState("");
  const [parallel, setParallel] = useState<boolean | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!settings) return;
    setModels((m) => m ?? settings.models);
    setExclude((x) => x ?? settings.source.exclude_dirs);
    setParallel((p) => p ?? settings.ingest.parallel);
  }, [settings]);

  // --- SRS -------------------------------------------------------------------
  const chooseSrs = (file: File) => {
    const problem = srsProblem(file, maxMb);
    setSrsFile(file);
    setSrsError(problem);
    setPreview(null);
    if (!problem && /\.(md|txt)$/i.test(file.name)) {
      file.text().then((t) => setPreview(t.split(/\r?\n/).slice(0, 12).join("\n")));
    }
  };
  const srsReady = srsMode === "upload" ? !!srsFile && !srsError : pasted.trim().length > 0;

  // --- Code: inspect as the source changes ----------------------------------------
  useEffect(() => {
    if (codeMode !== "zip") return;
    if (!zipFile) return runInspect(null);
    const form = new FormData();
    form.append("source_kind", "zip");
    form.append("zip", zipFile);
    if (exclude) form.append("exclude_dirs", JSON.stringify(exclude));
    runInspect(form);
  }, [codeMode, zipFile, exclude]);

  useEffect(() => {
    if (codeMode === "zip") return;
    const value = codeMode === "folder" ? folder.trim() : gitUrl.trim();
    if (!value) return runInspect(null);
    const t = setTimeout(() => {
      const form = new FormData();
      form.append("source_kind", codeMode);
      form.append(codeMode === "folder" ? "folder" : "git_url", value);
      if (exclude) form.append("exclude_dirs", JSON.stringify(exclude));
      runInspect(form);
    }, 500);
    return () => clearTimeout(t);
  }, [codeMode, folder, gitUrl, exclude]);

  const gitUrlInvalid = codeMode === "git" && gitUrl.trim() !== "" && !GIT_URL.test(gitUrl.trim());
  const stats = inspect.result?.stats ?? null;
  const blocking = inspect.result?.warnings.find((w) => w.level === "error");
  const codeReady =
    inspect.state === "done" && !blocking && (codeMode !== "git" || !gitUrlInvalid);

  // --- Plan and estimate -----------------------------------------------------------
  const components = stats?.components ?? null;
  const docSeconds = components != null ? components * SECONDS_PER_COMPONENT : null;
  const srsName = srsMode === "paste" ? "the pasted text" : srsFile?.name ?? "the SRS";
  const repoName =
    codeMode === "git" ? gitUrl.replace(/\/+$/, "").split("/").slice(-2).join("/") || "the repository"
      : codeMode === "zip" ? zipFile?.name ?? "the archive" : folder.split(/[\\/]/).filter(Boolean).pop() ?? "the folder";
  const large = inspect.result?.warnings.some((w) => w.code === "large_repo" || w.code === "many_components");
  const plan = [
    { text: `Fetch ${repoName} and parse ${components != null ? `${components} components` : "its components"}`, t: "~1 min" },
    { text: `Generate docstrings for ${components != null ? `~${components} components` : "each component"}`, t: docSeconds != null ? approx(docSeconds) : `~${SECONDS_PER_COMPONENT} s each`, warn: large },
    { text: `Extract requirements from ${srsName}, ${parallel === false ? "before the code lane" : "in parallel"}`, t: "a few min" },
    { text: "Pause for your review of uncertain requirements", t: "you" },
    { text: `Search, map and verify each requirement, ~${SECONDS_PER_REQUIREMENT} s each`, t: "" },
  ];

  const canStart = srsReady && codeReady && !submitting && !!settings;
  const hint = !srsReady && !codeReady
    ? "Add a requirements document and a codebase to start."
    : !srsReady ? (srsError ? "Fix the requirements document to start." : "Add a requirements document to start.")
      : !codeReady ? (blocking || inspect.state === "error" ? "Fix the codebase problem above to start." : inspect.state === "loading" ? "Checking the codebase…" : "Add a codebase to start.")
        : large ? "You can start anyway. Progress is saved if you cancel."
          : "You can leave this page. The run continues in the background.";

  const start = async () => {
    if (!canStart || !settings || !models || !exclude) return;
    setSubmitting(true);
    setSubmitError(null);
    const form = new FormData();
    form.append("source_kind", codeMode);
    if (srsMode === "upload" && srsFile) form.append("srs", srsFile);
    else form.append("srs", new File([pasted], "pasted_srs.md", { type: "text/markdown" }));
    if (codeMode === "zip" && zipFile) form.append("zip", zipFile);
    if (codeMode === "folder") form.append("folder", folder.trim());
    if (codeMode === "git") {
      form.append("git_url", gitUrl.trim());
      if (gitRef.trim()) form.append("git_ref", gitRef.trim());
    }
    form.append("overrides", JSON.stringify({ models, source: { exclude_dirs: exclude }, ingest: { parallel } }));
    try {
      const run = await api.form<RunCard>("/api/runs", form);
      await qc.invalidateQueries({ queryKey: keys.runs });
      navigate(`/runs/${run.run_id}/pipeline`);
    } catch (e) {
      setSubmitError((e as ApiError).message);
      setSubmitting(false);
    }
  };

  const pulled = health?.ollama.models ?? [];
  const modelOptions = (current: string) => Array.from(new Set([current, ...pulled])).sort();
  const missingModels = useMemo(
    () => (models && health?.ollama.ok ? ROLES.filter(({ role }) => !pulled.some((m) => m === models[role] || m === `${models[role]}:latest`)) : []),
    [models, health, pulled],
  );

  return (
    <div>
      <header className="border-b border-border bg-panel px-8 py-5">
        <div className="mb-0.5 text-xs text-fg3">
          <Link to="/" className="text-fg3">Runs</Link> / New
        </div>
        <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">New traceability run</h1>
      </header>

      <div className="flex max-w-[1280px] flex-col gap-6 px-8 pt-6 pb-12">
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(380px,1fr))" }}>
          {/* Requirements document */}
          <Panel
            id="srs-h"
            title="Requirements document"
            subtitle={`DOCX, PDF, Markdown or text · up to ${maxMb} MB`}
            action={
              <Segmented label="SRS input" value={srsMode} onChange={setSrsMode}
                options={[{ id: "upload", label: "Upload" }, { id: "paste", label: "Paste text" }]} />
            }
          >
            {srsMode === "paste" ? (
              <textarea
                value={pasted}
                onChange={(e) => setPasted(e.target.value)}
                placeholder={"FR-001 The system shall …\nFR-002 The system shall …"}
                aria-label="SRS text"
                className="min-h-[220px] flex-1 resize-y rounded-md border border-border-strong bg-panel p-3 font-mono text-xs leading-relaxed text-fg outline-none focus:border-accent"
              />
            ) : !srsFile ? (
              <DropZone accept={SRS_EXT.join(",")} onFile={chooseSrs}>
                <span aria-hidden="true" className="relative h-[34px] w-7 rounded-[3px] border-[1.5px] border-fg3">
                  <span className="absolute top-[9px] right-[5px] left-[5px] h-[1.5px] bg-fg3" />
                  <span className="absolute top-[15px] right-[9px] left-[5px] h-[1.5px] bg-fg3" />
                </span>
                <span className="font-medium">Drop your SRS here, or <span className="text-accent">browse</span></span>
                <span className="text-xs text-fg3">Text-based PDFs and DOCX work best. Scanned documents need OCR first.</span>
              </DropZone>
            ) : (
              <>
                <div className={`tl-in flex items-center gap-3 rounded-md border px-3 py-2.5 ${srsError ? "border-bad bg-bad-bg" : "border-border"}`}>
                  <FileBadge name={srsFile.name} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-[13px] font-medium">{srsFile.name}</div>
                    <div className="text-xs text-fg3">{fileSize(srsFile.size)}</div>
                  </div>
                  <label className="h-7 cursor-pointer rounded-md border border-border-strong bg-panel px-2.5 text-xs leading-[26px] hover:bg-hover">
                    Replace
                    <input type="file" hidden accept={SRS_EXT.join(",")} onChange={(e) => e.target.files?.[0] && chooseSrs(e.target.files[0])} />
                  </label>
                  <button aria-label="Remove file" onClick={() => { setSrsFile(null); setSrsError(null); setPreview(null); }}
                    className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent text-fg3 hover:text-fg"><XIcon /></button>
                </div>
                {srsError ? (
                  <Alert tone="error" title="Can’t use this file.">{srsError}</Alert>
                ) : preview != null ? (
                  <div>
                    <div className="mb-1.5 text-xs text-fg3">Preview · first lines</div>
                    <pre className="m-0 max-h-[180px] overflow-hidden rounded-md border border-border bg-code-bg p-3 font-mono text-xs leading-[1.7] whitespace-pre-wrap text-fg2">{preview}</pre>
                  </div>
                ) : (
                  <div className="text-xs text-fg3">The document is parsed when the run starts; problems such as a scanned PDF without a text layer show up on the pipeline page.</div>
                )}
              </>
            )}
          </Panel>

          {/* Codebase */}
          <Panel
            id="code-h"
            title="Codebase"
            subtitle="Python is supported in this version"
            action={
              <Segmented label="Code source" value={codeMode} onChange={setCodeMode}
                options={[{ id: "zip", label: "ZIP" }, { id: "folder", label: "Folder" }, { id: "git", label: "GitHub URL" }]} />
            }
          >
            {codeMode === "git" && (
              <>
                <Field label="Repository URL">
                  <TextInput mono value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} placeholder="https://github.com/owner/repo"
                    invalid={gitUrlInvalid || inspect.state === "error"} spellCheck={false} />
                </Field>
                <Field label="Branch or tag" hint="optional, defaults to the default branch">
                  <TextInput mono value={gitRef} onChange={(e) => setGitRef(e.target.value)} placeholder="main" spellCheck={false} />
                </Field>
              </>
            )}
            {codeMode === "folder" && (
              <Field label="Folder on this machine">
                <TextInput mono value={folder} onChange={(e) => setFolder(e.target.value)}
                  placeholder={"C:\\path\\to\\project"} invalid={inspect.state === "error"} spellCheck={false} />
              </Field>
            )}
            {codeMode === "zip" && (
              zipFile ? (
                <div className="tl-in flex items-center gap-3 rounded-md border border-border px-3 py-2.5">
                  <FileBadge name={zipFile.name} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-[13px] font-medium">{zipFile.name}</div>
                    <div className="text-xs text-fg3">{fileSize(zipFile.size)}</div>
                  </div>
                  <button aria-label="Remove archive" onClick={() => setZipFile(null)}
                    className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent text-fg3 hover:text-fg"><XIcon /></button>
                </div>
              ) : (
                <DropZone accept=".zip" onFile={setZipFile} minHeight={120}>
                  <span className="font-medium">Drop a ZIP of the code here, or <span className="text-accent">browse</span></span>
                  <span className="text-xs text-fg3">GitHub’s “Download ZIP” works as is.</span>
                </DropZone>
              )
            )}

            {inspect.state === "idle" && codeMode === "git" && (
              <Alert tone="info">Paste a public repository URL, or switch to ZIP or Folder for private code. Nothing leaves this machine except the git fetch.</Alert>
            )}
            {gitUrlInvalid && <Alert tone="error" title="Not a repository URL.">Use an https:// address, e.g. https://github.com/owner/repo.</Alert>}
            {inspect.state === "loading" && <div className="text-xs text-fg3">Checking the codebase…</div>}
            {inspect.state === "error" && !gitUrlInvalid && <Alert tone="error" title="Can’t use this source.">{inspect.error}</Alert>}
            {inspect.state === "done" && stats && (
              <div className="tl-in grid grid-cols-4 rounded-md border border-border">
                <Stat label="Python files" value={stats.python_files.toLocaleString()} />
                <Stat label="Components" value={stats.components.toLocaleString()} />
                <Stat label="Lines" value={stats.python_lines.toLocaleString()} />
                <Stat label="Size" value={fileSize(stats.bytes)} last />
              </div>
            )}
            {inspect.state === "done" && inspect.result?.note && <Alert tone="info">{inspect.result.note}</Alert>}
            {inspect.result?.warnings.map((w) => (
              <Alert key={w.code} tone={w.level === "error" ? "error" : "warn"}
                title={w.code === "large_repo" || w.code === "many_components" ? "Large repository." : w.level === "error" ? "Can’t trace this code." : undefined}>
                {w.message}
                {w.code === "large_repo" && docSeconds != null && ` Docstrings alone would take about ${approx(docSeconds).replace("~", "")}. Exclude folders under Advanced to reduce it.`}
              </Alert>
            ))}
            {inspect.state === "done" && stats && !inspect.result?.warnings.length && (
              <Alert tone="ok">Ready: {stats.python_files} Python files, {stats.components} components.</Alert>
            )}
          </Panel>
        </div>

        {/* Advanced */}
        <section className="rounded-lg border border-border bg-panel">
          <button onClick={() => setAdvOpen((o) => !o)} aria-expanded={advOpen}
            className="flex w-full cursor-pointer items-center gap-2.5 border-0 bg-transparent px-4 py-3.5 text-left">
            <span className="inline-block text-[10px] text-fg3 transition-transform duration-150 ease-out"
              style={{ transform: advOpen ? "rotate(90deg)" : "none" }}>▶</span>
            <span className="font-semibold">Advanced</span>
            <span className="text-xs text-fg3">Models, exclusions, lanes</span>
          </button>
          {advOpen && models && exclude && (
            <div className="tl-in grid gap-6 pr-4 pb-4 pl-9" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))" }}>
              <div className="flex flex-col gap-3">
                <div className="text-xs font-medium text-fg3">Models (Ollama)</div>
                {ROLES.map(({ role, label }) => (
                  <label key={role} className="flex flex-col gap-1 text-[13px]">
                    {label}
                    <select value={models[role]} onChange={(e) => setModels({ ...models, [role]: e.target.value })}
                      className="h-8 cursor-pointer rounded-md border border-border-strong bg-panel px-2 font-mono text-[13px] text-fg">
                      {modelOptions(models[role]).map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </label>
                ))}
                {missingModels.length > 0 && (
                  <Alert tone="warn" title="Not pulled:">
                    {missingModels.map(({ role }) => models[role]).join(", ")}. Run <code className="font-mono">ollama pull</code> first, or pick another model.
                  </Alert>
                )}
              </div>
              <div className="flex flex-col gap-2.5">
                <div className="text-xs font-medium text-fg3">Exclude folders</div>
                <div className="flex flex-wrap gap-1.5">
                  {exclude.map((x) => (
                    <span key={x} className="inline-flex h-[26px] items-center gap-1.5 rounded border border-border-strong pr-1.5 pl-2.5 font-mono text-xs">
                      {x}
                      <button aria-label={`Stop excluding ${x}`} onClick={() => setExclude(exclude.filter((y) => y !== x))}
                        className="flex cursor-pointer items-center border-0 bg-transparent px-0.5 text-fg3 hover:text-fg"><XIcon /></button>
                    </span>
                  ))}
                </div>
                <form className="flex gap-1.5" onSubmit={(e) => {
                  e.preventDefault();
                  const p = newPattern.trim().replace(/[\\/]+$/, "");
                  if (p && !exclude.includes(p)) setExclude([...exclude, p]);
                  setNewPattern("");
                }}>
                  <TextInput mono value={newPattern} onChange={(e) => setNewPattern(e.target.value)} placeholder="folder name, e.g. tests"
                    className="h-[26px] flex-1 text-xs" aria-label="Folder to exclude" />
                  <button type="submit" className="h-[26px] cursor-pointer rounded border border-dashed border-border-strong bg-transparent px-2.5 text-xs text-fg2 hover:text-fg">+ Add</button>
                </form>
                <div className="text-xs text-fg3">Folder names are skipped anywhere in the tree. The size check above updates as you change them.</div>
              </div>
              <div className="flex flex-col gap-2.5">
                <div className="text-xs font-medium text-fg3">Ingestion lanes</div>
                {[
                  { v: true, title: "Code and SRS in parallel", text: "Fastest when the GPU can hold both models at once." },
                  { v: false, title: "SRS first, then code", text: "Better on a small GPU: Ollama does not have to swap models. You can review sooner." },
                ].map((o) => (
                  <label key={String(o.v)} className="flex cursor-pointer items-start gap-2.5 text-[13px]">
                    <input type="radio" name="lanes" checked={parallel === o.v} onChange={() => setParallel(o.v)} className="mt-1 accent-[var(--accent)]" />
                    <span>
                      <span className="block font-medium">{o.title}</span>
                      <span className="text-xs text-fg3">{o.text}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Summary */}
        <section aria-labelledby="sum-h" className="grid rounded-lg border border-border bg-panel" style={{ gridTemplateColumns: "minmax(0,1fr) 300px" }}>
          <div className="border-r border-border px-5 py-4">
            <h2 id="sum-h" className="m-0 mb-3 text-sm font-semibold">What will happen</h2>
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0 text-[13px]">
              {plan.map((p, i) => (
                <li key={p.text} className="grid items-baseline gap-2" style={{ gridTemplateColumns: "24px 1fr auto" }}>
                  <span className="font-mono text-xs font-medium text-fg3">{String(i + 1).padStart(2, "0")}</span>
                  <span style={{ color: p.warn ? "var(--part)" : "var(--fg)" }}>{p.text}</span>
                  <span className="font-mono text-xs text-fg3">{p.t}</span>
                </li>
              ))}
            </ol>
          </div>
          <div className="flex flex-col gap-3 px-5 py-4">
            <div>
              <div className="text-xs text-fg3">Docstring generation</div>
              <div className="font-mono text-2xl leading-[1.3] font-medium tracking-[-0.02em]">{docSeconds != null ? approx(docSeconds) : "—"}</div>
              <div className="text-xs text-fg3">plus extraction, your review and ~{SECONDS_PER_REQUIREMENT} s per requirement</div>
            </div>
            {models && (
              <div className="text-xs text-fg3">
                Local models: <span className="font-mono text-fg2">{Array.from(new Set(Object.values(models))).join(", ")}</span>
              </div>
            )}
            <button disabled={!canStart} onClick={start}
              className="h-9 cursor-pointer rounded-md border font-medium disabled:cursor-not-allowed"
              style={{
                borderColor: canStart ? "var(--accent)" : "var(--hover)",
                background: canStart ? "var(--accent)" : "var(--hover)",
                color: canStart ? "var(--accent-fg)" : "var(--fg3)",
              }}>
              {submitting ? "Starting…" : "Start traceability run"}
            </button>
            {submitError ? <Alert tone="error">{submitError}</Alert> : (
              <div className="text-xs" style={{ color: blocking || srsError ? "var(--bad)" : "var(--fg3)" }}>{hint}</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
