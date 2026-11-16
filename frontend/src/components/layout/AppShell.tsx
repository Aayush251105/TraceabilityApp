import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";

const KEY = "tl-sidebar";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === "collapsed";
  } catch {
    return false;
  }
}

/** Sidebar open/collapsed, remembered per browser; "[" toggles it (outside text fields). */
export function useSidebar(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = useCallback(() => setCollapsed((c) => !c), []);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, collapsed ? "collapsed" : "open");
    } catch {
      /* storage blocked: the choice lasts for this page only */
    }
  }, [collapsed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName?.toLowerCase();
      if (e.key !== "[" || e.ctrlKey || e.metaKey || e.altKey || tag === "input" || tag === "textarea" || tag === "select" || el?.isContentEditable) return;
      e.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
  return [collapsed, toggle];
}

export function AppShell() {
  const [collapsed, toggle] = useSidebar();
  return (
    <div className="flex min-h-screen">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

/** Page title bar: title, one-line description, optional actions on the right. */
export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex items-start justify-between gap-6 border-b border-border bg-panel px-8 py-5">
      <div className="min-w-0">
        <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">{title}</h1>
        {subtitle && <div className="text-[13px] text-fg3">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-none items-center gap-2">{actions}</div>}
    </header>
  );
}
