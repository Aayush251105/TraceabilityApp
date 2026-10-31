import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
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
