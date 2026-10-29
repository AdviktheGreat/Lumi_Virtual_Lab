"use client";

import { PageHeader } from "@/components/page-header";

// A page of the lab's own, such as Data or Papers: a large title with what the page is for, or, when one thing on it is
// open, the title in the bar over it so that the thing is what the page shows
export function PageFrame({ title, intro, children }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  const open = intro === undefined;

  return (
    <>
      <PageHeader className={open ? undefined : "border-transparent"}>
        {open && <h1 className="min-w-0 flex-1 truncate font-serif text-lg font-medium tracking-tight">{title}</h1>}
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-12 px-5 pb-16 pt-4 sm:px-6">
          {!open && (
            <div className="flex flex-col gap-3">
              <h1 className="font-serif text-4xl font-medium tracking-tight">{title}</h1>
              <p className="max-w-2xl text-[15px] leading-7 text-muted-foreground">{intro}</p>
            </div>
          )}
          {children}
        </div>
      </div>
    </>
  );
}
