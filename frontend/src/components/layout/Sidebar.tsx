import { NavLink, useMatch } from "react-router-dom";

import { useHealth, useRuns } from "../../api/hooks";
import type { RunCard } from "../../api/types";
import { runMeta } from "../../lib/status";
import { useTheme } from "../../lib/theme";

function Item({ to, label, badge, end }: { to: string; label: string; badge?: number; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        "flex h-[30px] items-center justify-between rounded-[5px] px-2 no-underline hover:bg-hover hover:no-underline " +
        (isActive ? "bg-hover font-medium text-fg" : "text-fg2")
      }
    >
      <span>{label}</span>
      {badge ? (
        <span className="rounded-[9px] bg-rev-bg px-1.5 font-mono text-[11px] leading-[18px] font-medium text-rev">
          {badge}
        </span>
      ) : null}
    </NavLink>
  );
}

function recentStatus(run: RunCard): string {
  if (run.status === "completed") {
    const supported = run.summary?.status_counts?.supported ?? 0;
    return `${supported}/${run.summary?.requirements ?? 0}`;
  }
  if (run.status === "paused") return run.review.open ? "Needs input" : "Ready";
  return runMeta(run.status).label;
}

/** The run the "Run #N" section points at: the one in the URL, else the most recent. */
function useCurrentRun(runs: RunCard[] | undefined): RunCard | undefined {
  const match = useMatch("/runs/:runId/*");
  const id = match ? Number(match.params.runId) : null;
  return (id != null && runs?.find((r) => r.run_id === id)) || runs?.[0];
}

export function Sidebar() {
  const { data: runs } = useRuns();
  const { data: health, isError: healthDown } = useHealth();
  const [theme, toggleTheme] = useTheme();
  const current = useCurrentRun(runs);

  const ollamaOk = !!health?.ollama.ok;
  const ollamaLabel = healthDown
    ? "Server unreachable"
    : !health
      ? "Checking Ollama…"
      : ollamaOk
        ? `Ollama connected · ${health.ollama_host.replace(/^https?:\/\//, "").replace(/:\d+$/, "")}`
        : "Ollama unreachable";

  return (
    <nav
      aria-label="Primary"
      className="sticky top-0 flex h-screen w-[232px] flex-none flex-col overflow-y-auto border-r border-border bg-sidebar text-[13px]"
    >
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
        <div className="relative h-[18px] w-[18px] flex-none rounded bg-fg">
          <div className="absolute top-1 left-1 h-2.5 w-1.5 rounded-[1px] bg-sidebar" />
        </div>
        <span className="text-sm font-semibold tracking-[-0.01em]">Tracelight</span>
      </div>

      <div className="flex flex-col gap-px px-2 py-1">
        <Item to="/" end label="Runs" />
        <Item to="/new" label="New run" />
      </div>

      {current && (
        <>
          <div className="flex justify-between px-4 pt-4 pb-1.5 text-[11px] font-medium text-fg3">
            <span>Run #{current.run_id}</span>
            {current.source.commit_sha && <span className="font-mono">{current.source.commit_sha.slice(0, 7)}</span>}
          </div>
          <div className="flex flex-col gap-px px-2">
            <Item to={`/runs/${current.run_id}/pipeline`} label="Live pipeline" />
            <Item to={`/runs/${current.run_id}/review`} label="Review" badge={current.review.open} />
            <Item to={`/runs/${current.run_id}/results`} label="Results" />
            <Item to={`/runs/${current.run_id}/code`} label="Code view" />
          </div>
        </>
      )}

      {runs && runs.length > 0 && (
        <>
          <div className="px-4 pt-4 pb-1.5 text-[11px] font-medium text-fg3">Recent runs</div>
          <div className="flex flex-col gap-px px-2">
            {runs.slice(0, 5).map((r) => {
              const meta = runMeta(r.status);
              const to = r.status === "completed" ? "results" : r.status === "paused" ? "review" : "pipeline";
              return (
                <NavLink
                  key={r.run_id}
                  to={`/runs/${r.run_id}/${to}`}
                  className="flex h-7 items-center gap-2 rounded-[5px] px-2 text-fg2 no-underline hover:bg-hover hover:no-underline"
                >
                  <span className="h-2 w-2 flex-none" style={{ borderRadius: meta.r, background: meta.c }} />
                  <span className="flex-1 truncate">Run #{r.run_id}</span>
                  <span className="text-[11px] text-fg3">{recentStatus(r)}</span>
                </NavLink>
              );
            })}
          </div>
        </>
      )}

      <div className="flex-1" />

      <div className="flex flex-col gap-px border-t border-border px-2 pt-2 pb-2">
        <Item to="/components" label="Component sheet" />
        <Item to="/settings" label="Settings" />
        <button
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="flex h-[30px] cursor-pointer items-center justify-between rounded-[5px] border-0 bg-transparent px-2 text-[13px] text-fg2 hover:bg-hover"
        >
          <span>Theme</span>
          <span className="font-mono text-[11px] font-medium text-fg3">{theme === "dark" ? "Dark" : "Light"}</span>
        </button>
        <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-fg3" role="status">
          <span
            className="h-[7px] w-[7px] flex-none rounded-full"
            style={{ background: ollamaOk ? "var(--ok)" : health || healthDown ? "var(--bad)" : "var(--fg3)" }}
          />
          <span className="truncate">{ollamaLabel}</span>
        </div>
      </div>
    </nav>
  );
}
