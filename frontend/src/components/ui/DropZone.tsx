import { useRef, useState, type ReactNode } from "react";

/** A large dashed drop target that also opens the file picker. */
export function DropZone({ accept, onFile, children, minHeight = 220 }: {
  accept: string;
  onFile: (file: File) => void;
  children: ReactNode;
  minHeight?: number;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) onFile(file);
        }}
        className="flex flex-1 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-[1.5px] border-dashed p-6 transition-colors duration-150 hover:border-accent hover:bg-accent-bg"
        style={{
          minHeight,
          borderColor: over ? "var(--accent)" : "var(--border-strong)",
          background: over ? "var(--accent-bg)" : "var(--subtle)",
        }}
      >
        {children}
      </button>
      <input
        ref={input}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </>
  );
}

/** Document icon with the file type printed at the bottom (PDF in red, others neutral). */
export function FileBadge({ name }: { name: string }) {
  const ext = (name.split(".").pop() || "").toUpperCase().slice(0, 4);
  return (
    <span
      className="flex h-[38px] w-8 flex-none items-end justify-center rounded-[3px] border border-border-strong bg-panel pb-[3px] font-mono text-[8px] font-semibold"
      style={{ color: ext === "PDF" ? "var(--bad)" : "var(--fg2)" }}
    >
      {ext}
    </span>
  );
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
