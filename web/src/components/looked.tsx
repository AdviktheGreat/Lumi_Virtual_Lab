"use client";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/errors";
import type { Loaded } from "@/lib/use-settings-data";

// What a part of a page that is made of what the server holds shows until it has been asked for, and if it could not be
export function Looked<T>({
  state,
  label,
  failure,
  onRetry,
  children,
}: {
  state: Loaded<T>;
  // What is being looked at, which a screen reader is told while it is
  label: string;
  // What it was that could not be looked at, which says what is wrong with it
  failure: string;
  onRetry: () => void;
  children: (value: T) => React.ReactNode;
}) {
  if (state.kind === "loading") {
    return (
      <div className="flex flex-col gap-2" role="status" aria-busy="true" aria-label={label}>
        {[0, 1].map((row) => (
          <Skeleton key={row} className="h-16 w-full" />
        ))}
      </div>
    );
  }
  if (state.kind === "failed") {
    return (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-sm text-destructive">
          {failure} {describeError(state.error)}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  }

  return children(state.value);
}
