import { Link } from "react-router-dom";

import { PageHeader } from "../components/layout/AppShell";

export function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" subtitle="The address does not match a page in Tracelight." />
      <div className="px-8 py-6 text-[13px] text-fg2">
        <Link to="/">Go to runs</Link>
      </div>
    </>
  );
}
