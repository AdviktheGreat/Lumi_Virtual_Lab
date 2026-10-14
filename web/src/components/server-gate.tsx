"use client";

import { KeyRound, ServerOff, WifiOff } from "lucide-react";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { useServer } from "@/components/server-provider";

// Shows the pages once the server has answered, and what is wrong until it has
export function ServerGate({ children }: { children: React.ReactNode }) {
  const { server, check } = useServer();
  // A server that goes away while the page is open leaves what is on it, which is read as it was. The pages are in the
  // same place whether it is there or not, so that they are not made again when it comes back.
  if (server.status === "ready" || (server.status === "unreachable" && server.lost)) {
    return (
      <div className="flex h-dvh flex-col">
        {server.status === "unreachable" && (
          <div
            role="status"
            className="flex shrink-0 items-center justify-center gap-2 bg-warning/15 px-3 py-1.5 text-sm text-foreground"
          >
            <WifiOff className="size-4 text-warning" aria-hidden />
            The server cannot be reached. Trying again…
          </div>
        )}
        <div className="min-h-0 flex-1">{children}</div>
      </div>
    );
  }
  if (server.status === "checking") {
    return (
      <main className="flex h-dvh items-center justify-center" aria-busy="true">
        <h1 className="sr-only">Looking for the server</h1>
        <Brand className="animate-pulse" />
      </main>
    );
  }

  const unauthorized = server.status === "unauthorized";

  return (
    <main className="flex h-dvh items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <Brand />
        <div className="flex size-12 items-center justify-center rounded-full bg-muted">
          {unauthorized ? (
            <KeyRound className="size-5 text-muted-foreground" aria-hidden />
          ) : (
            <ServerOff className="size-5 text-muted-foreground" aria-hidden />
          )}
        </div>
        <h1 className="text-lg font-semibold">{unauthorized ? "Open the link the server printed" : "The server cannot be reached"}</h1>
        <p className="text-sm text-muted-foreground">
          {unauthorized
            ? "The server keeps to the person who started it. Its link has a token in it, which is printed in the terminal when it starts. Opening that link lets this browser in."
            : "Start it with virtual-lab-server, then open the link it prints. This page tries again by itself."}
        </p>
        <Button variant="outline" onClick={() => void check()}>
          Try again
        </Button>
      </div>
    </main>
  );
}
