"use client";

import Link from "next/link";
import { PageSection } from "@/components/page-section";
import { SURVEYS_ADDRESS, type PaperView } from "@/lib/papers";
import { cn } from "@/lib/utils";

const VIEWS: { view: PaperView; label: string; href: string }[] = [
  { view: "agents", label: "Agents", href: "/papers" },
  { view: "surveys", label: "Surveys", href: SURVEYS_ADDRESS },
];

// The two parts of the page, each reached by an address of its own, as the pages of the rail are
export function PaperAgentsNav({ view }: { view: PaperView }) {
  return (
    <nav aria-label="PaperAgents" className="-mb-6 flex gap-1 border-b border-border">
      {VIEWS.map((part) => {
        const current = part.view === view;

        return (
          <Link
            key={part.view}
            href={part.href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "-mb-px rounded-t-sm border-b-2 px-3 py-2 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
              current ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {part.label}
          </Link>
        );
      })}
    </nav>
  );
}

// The agents there are, which is none until one can be made
export function Agents() {
  return (
    <PageSection title="Agents">
      <div className="flex flex-col gap-2 rounded-xl border border-dashed border-border p-5" data-testid="paper-agents-empty">
        <p className="text-sm font-medium">There are no PaperAgents yet</p>
        <p className="text-sm text-muted-foreground">
          A PaperAgent is one paper made usable: its text read, with each claim traced to the place it is made, a note of what its
          method was tested on, and tools built from the code that came with it. They cannot be made yet.
        </p>
        <p className="text-sm text-muted-foreground">
          What can be done now is in{" "}
          <Link href={SURVEYS_ADDRESS} className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            Surveys
          </Link>
          , which read many papers for the tasks, databases, and software they share.
        </p>
      </div>
    </PageSection>
  );
}
