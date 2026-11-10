// A block of text that is long, which is scrolled and can be reached with the keyboard
export function Printed({ label, text }: { label: string; text: string }) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="max-h-56 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <pre className="whitespace-pre-wrap break-words font-mono text-xs">{text}</pre>
    </div>
  );
}
