import { PageHeader } from "../components/layout/AppShell";

/** Pages not built yet (they arrive one step at a time). */
export function Placeholder({ title, step }: { title: string; step: string }) {
  return (
    <>
      <PageHeader title={title} subtitle={`Arrives in ${step}.`} />
      <div className="px-8 py-6 text-[13px] text-fg3">
        The backend for this page is ready; the screen is built in {step}.
      </div>
    </>
  );
}
