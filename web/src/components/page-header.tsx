"use client";

import { Menu, PanelLeftOpen } from "lucide-react";
import { useShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// The top of a page: what opens the sidebar where it is not shown beside the page, then what the page puts there
export function PageHeader({ children, className }: { children?: React.ReactNode; className?: string }) {
  const { sidebarShown, toggleSidebar, setDrawerOpen } = useShell();

  return (
    <header className={cn("flex h-12 shrink-0 items-center gap-2 border-b border-border px-3", className)}>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Show the conversations"
        onClick={() => setDrawerOpen(true)}
        className="md:hidden"
      >
        <Menu className="size-4" />
      </Button>
      {!sidebarShown && (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Show the sidebar"
          onClick={toggleSidebar}
          className="max-md:hidden"
        >
          <PanelLeftOpen className="size-4" />
        </Button>
      )}
      {children}
    </header>
  );
}
