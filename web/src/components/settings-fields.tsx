import { cn } from "@/lib/utils";

// A setting: what it is called, what a person should know to choose it, and what is wrong with what they chose. The
// control is given the id, and the ids of the hint and the problem to be described by.
export function Field({
  id,
  label,
  hint,
  problem,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: React.ReactNode;
  problem?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && (
        <p id={hintId(id)} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {problem && (
        <p id={problemId(id)} role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
    </div>
  );
}

const hintId = (id: string) => `${id}-hint`;
const problemId = (id: string) => `${id}-problem`;

// What a control says that it is described by, which is the hint, and the problem when there is one
export function describedBy(id: string, { hint, problem }: { hint?: boolean; problem?: boolean }): string | undefined {
  const ids = [hint ? hintId(id) : null, problem ? problemId(id) : null].filter(Boolean);

  return ids.length > 0 ? ids.join(" ") : undefined;
}

// A group of settings that go together, and are named when the part of the settings they are in is not name enough
export function Section({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      {title && <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>}
      {children}
    </section>
  );
}

// A note on how a setting works, which is more than a hint is
export function Aside({ tone = "muted", children }: { tone?: "muted" | "warning"; children: React.ReactNode }) {
  return (
    <p className={cn("rounded-lg px-3 py-2 text-xs", tone === "warning" ? "bg-warning/15 text-foreground" : "bg-muted/60 text-muted-foreground")}>
      {children}
    </p>
  );
}
