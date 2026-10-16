"use client";

import { useId } from "react";

// A part of a page that has a name, and what it is for if that is not plain
export function PageSection({ title, intro, children }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={id} className="text-base font-semibold">
          {title}
        </h2>
        {intro && <p className="text-sm text-muted-foreground">{intro}</p>}
      </div>
      {children}
    </section>
  );
}
