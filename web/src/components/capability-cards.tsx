"use client";

import { useId, useState } from "react";
import { ArrowUpRight, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// A way to begin: what it is about, what to call it, the question it puts, and what the lab is likely to reach for to
// answer it
export interface Capability {
  category: string;
  title: string;
  prompt: string;
  uses?: string;
}

export const CAPABILITIES: Capability[] = [
  {
    category: "Gene editing",
    title: "Base editing",
    prompt: "Explain how CRISPR base editors work and where they fall short, and what would improve them.",
  },
  {
    category: "Experiment design",
    title: "Experiment design",
    prompt: "Plan an experiment to test whether knocking down a gene changes T-cell exhaustion, with controls.",
  },
  {
    category: "Methods",
    title: "Method comparison",
    prompt: "Compare structure-prediction and physics-based approaches to docking an antibody to its antigen.",
  },
  {
    category: "Statistical genetics",
    title: "Analysis plan",
    prompt: "Draft an analysis plan for a case-control GWAS of 5,000 samples, from quality control to follow-up.",
  },
  {
    category: "Literature",
    title: "Literature scan",
    prompt:
      "Search the literature for recent advances in prime editing efficiency, and summarise the three most important papers, with their IDs.",
    uses: "Paperclip",
  },
  {
    category: "Drug discovery",
    title: "Compounds for a target",
    prompt: "Using ChEMBL, find the best-characterised inhibitors of EGFR, and compare their potency and selectivity.",
    uses: "Code",
  },
  {
    category: "Protein design",
    title: "Structure prediction",
    prompt: "Predict the structure of this protein with ESMFold, and tell me how confident it is: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ",
    uses: "Proto",
  },
  {
    category: "Data analysis",
    title: "Data lake question",
    prompt:
      "From the data lake, find the genes with the most interactions in affinity_capture-ms.parquet, and describe what they do.",
    uses: "Data lake",
  },
];

// Which of the capabilities a search is for: those with all of its words in what they are about
export function matchingCapabilities(all: Capability[], typed: string): Capability[] {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);

  return all.filter((item) => {
    const text = `${item.category} ${item.title} ${item.prompt} ${item.uses ?? ""}`.toLowerCase();

    return words.every((word) => text.includes(word));
  });
}

export function CapabilityCards({ onChoose }: { onChoose: (prompt: string) => void }) {
  const [typed, setTyped] = useState("");
  const heading = useId();
  const shown = matchingCapabilities(CAPABILITIES, typed);

  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 id={heading} className="font-serif text-xl font-medium tracking-tight">
          Ways to begin
        </h2>
        <div className="relative w-44">
          <Search aria-hidden className="pointer-events-none absolute left-3 top-2.5 size-3.5 text-muted-foreground" />
          <Input
            type="search"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Search…"
            aria-label="Search the ways to begin"
            autoComplete="off"
            className="h-8 rounded-full bg-card pl-8 text-xs [&::-webkit-search-cancel-button]:appearance-none"
          />
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Nothing here matches those words.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Examples">
          {shown.map((item) => (
            <li key={item.title}>
              <button
                type="button"
                onClick={() => onChoose(item.prompt)}
                className={cn(
                  "group flex h-full w-full flex-col gap-1.5 rounded-2xl border border-border bg-card p-4 text-left outline-none transition-[border-color,background-color,box-shadow]",
                  "hover:border-ring/60 hover:bg-accent/40 hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/40",
                )}
              >
                <span className="text-xs text-muted-foreground">{item.category}</span>
                <span className="font-serif text-[17px] font-semibold leading-snug">{item.title}</span>
                <span className="line-clamp-3 text-[13px] leading-5 text-muted-foreground">{item.prompt}</span>
                <span className="mt-auto flex items-center justify-between pt-2 text-xs font-medium">
                  <span className="flex items-center gap-0.5 text-foreground">
                    Start
                    <ArrowUpRight aria-hidden className="size-3.5 transition-transform group-hover:-translate-y-px group-hover:translate-x-px" />
                  </span>
                  {item.uses && (
                    <Badge variant="outline" className="rounded-md px-1.5 text-[10px] font-medium text-muted-foreground">
                      {item.uses}
                    </Badge>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
