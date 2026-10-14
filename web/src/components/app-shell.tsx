"use client";

import { createContext, Suspense, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { ChatsProvider } from "@/components/chats-provider";
import { SettingsProvider } from "@/components/settings-provider";
import { SetupProvider } from "@/components/setup-provider";
import { Sidebar } from "@/components/sidebar";
import { cn } from "@/lib/utils";

interface ShellContext {
  // Whether the sidebar is shown beside the page, on a screen wide enough to
  sidebarShown: boolean;
  toggleSidebar: () => void;
  // Whether it is open over the page, on a screen that is not
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
}

const Context = createContext<ShellContext | null>(null);

const KEY = "vl-sidebar";
const CHANGED = "vl-sidebar-changed";

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);

  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function shownSnapshot(): boolean {
  try {
    return localStorage.getItem(KEY) !== "hidden";
  } catch {
    return true;
  }
}

export function useShell(): ShellContext {
  const value = useContext(Context);
  if (value === null) throw new Error("useShell needs the AppShell");

  return value;
}

// The page on a close look of what the address says, so that moving to another conversation closes the drawer
function useAddress(): string {
  const pathname = usePathname();
  const query = useSearchParams().toString();

  return `${pathname}?${query}`;
}

function DrawerCloser({ onClose }: { onClose: () => void }) {
  const address = useAddress();
  useEffect(() => {
    onClose();
  }, [address, onClose]);

  return null;
}

function useEscapeToClose(open: boolean, onClose: () => void): void {
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      // A menu, a dialog, or a box that has something to give up takes its own Escape, and says so by handling it
      if (event.key === "Escape" && !event.defaultPrevented) onClose();
    };
    document.addEventListener("keydown", close);

    return () => document.removeEventListener("keydown", close);
  }, [open, onClose]);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const sidebarShown = useSyncExternalStore(subscribe, shownSnapshot, () => true);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleSidebar = useCallback(() => {
    try {
      localStorage.setItem(KEY, shownSnapshot() ? "hidden" : "shown");
    } catch {
      // Not kept, so it is as it was on the next visit
    }
    window.dispatchEvent(new Event(CHANGED));
  }, []);

  const value = useMemo(
    () => ({ sidebarShown, toggleSidebar, drawerOpen, setDrawerOpen }),
    [sidebarShown, toggleSidebar, drawerOpen],
  );
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  useEscapeToClose(drawerOpen, closeDrawer);

  return (
    <Context.Provider value={value}>
      <ChatsProvider>
        <SettingsProvider>
          <SetupProvider>
            <Suspense>
              <DrawerCloser onClose={closeDrawer} />
            </Suspense>
            <div className="flex h-full overflow-hidden">
              {drawerOpen && (
                <div
                  className="fixed inset-0 z-30 bg-black/40 md:hidden"
                  onClick={() => setDrawerOpen(false)}
                  aria-hidden
                />
              )}
              <aside
                aria-label="Sidebar"
                className={cn(
                  "fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[transform,visibility] duration-200 md:static md:z-auto md:translate-x-0",
                  // Off the screen is also out of the tab order
                  drawerOpen ? "translate-x-0" : "-translate-x-full max-md:invisible",
                  !sidebarShown && "md:hidden",
                )}
              >
                <Suspense>
                  <Sidebar />
                </Suspense>
              </aside>
              <main className="flex min-w-0 flex-1 flex-col bg-background">{children}</main>
            </div>
          </SetupProvider>
        </SettingsProvider>
      </ChatsProvider>
    </Context.Provider>
  );
}
