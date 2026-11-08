"use client";

import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/utils";

// A page of the lab's own, such as Data or PaperAgents: a large title with what the page is for, or, when one thing on it is
// open, the title in the bar over it so that the thing is what the page shows. A page of cards is wide, and may have a
// button beside its title.
export function PageFrame({
  title,
  intro,
  action,
  wide = false,
  children,
}: {
  title: string;
  intro?: React.ReactNode;
  action?: React.ReactNode;
  wide?: boolean;
  children: React.ReactNode;
}) {
  const open = intro === undefined;

  return (
    <>
      <PageHeader className={open ? undefined : "border-transparent"}>
        {open && <h1 className="min-w-0 flex-1 truncate font-serif text-lg font-medium tracking-tight">{title}</h1>}
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn("mx-auto flex w-full flex-col gap-12 px-5 pb-16 pt-4 sm:px-6", wide ? "max-w-5xl" : "max-w-3xl")}>
          {!open && (
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-4">
                <h1 className="font-serif text-4xl font-medium tracking-tight">{title}</h1>
                {action}
              </div>
              <p className="max-w-2xl text-[15px] leading-7 text-muted-foreground">{intro}</p>
            </div>
          )}
          {children}
        </div>
      </div>
    </>
  );
}
