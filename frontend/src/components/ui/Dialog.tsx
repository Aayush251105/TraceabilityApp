import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "./Button";

/** Modal confirmation. Escape and the backdrop cancel; focus starts on the safe choice. */
export function ConfirmDialog({ title, children, confirmLabel, cancelLabel = "Cancel", destructive, busy, onConfirm, onCancel }: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const safe = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    safe.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div onClick={onCancel} className="tl-in fixed inset-0 z-10 flex items-center justify-center p-6"
      style={{ background: "rgba(10,10,12,.45)", animationDuration: "150ms" }}>
      <div role="dialog" aria-modal="true" aria-labelledby="dlg-title" onClick={(e) => e.stopPropagation()}
        className="w-[440px] max-w-full rounded-[10px] border border-border bg-panel shadow-panel">
        <div className="px-5 pt-5 pb-3">
          <h2 id="dlg-title" className="m-0 mb-2 text-base font-semibold">{title}</h2>
          <div className="text-[13px] leading-relaxed text-fg2">{children}</div>
        </div>
        <div className="flex justify-end gap-2 px-5 pt-3 pb-5">
          <Button ref={safe} onClick={onCancel}>{cancelLabel}</Button>
          <Button variant={destructive ? "destructive" : "primary"} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
