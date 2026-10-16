// Text that was asked or said, in a box of its own that scrolls and can be reached from a keyboard
export function Text({ label, children }: { label: string; children: string }) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-medium">{label}</h3>
      <pre
        tabIndex={0}
        aria-label={label}
        className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 p-2 font-sans text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {children}
      </pre>
    </div>
  );
}

// What the scientists said in turn, each in a box, and whether what is shown is cut short
export function Turns({
  label,
  turns,
  truncated,
}: {
  label: string;
  turns: { agent: string; message: string }[];
  truncated: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-xs font-medium">{label}</h3>
      <ol aria-label={label} className="flex flex-col gap-2">
        {turns.map((turn, number) => (
          <li key={number} className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">{turn.agent}</span>
            <pre
              tabIndex={0}
              aria-label={`${turn.agent} said`}
              className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 p-2 font-sans text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {turn.message}
            </pre>
          </li>
        ))}
      </ol>
      {truncated && <p className="text-xs text-muted-foreground">What was said is cut short here.</p>}
    </div>
  );
}
