"use client";

import { ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// What marks a custom program in the header, and opens what it was told to do
export function InstructionsButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      onClick={onClick}
      title="Show the instructions of this program"
      data-testid="program-instructions-button"
      className="shrink-0 gap-1.5 rounded-4xl"
    >
      <ScrollText className="size-3" aria-hidden />
      Custom program
    </Button>
  );
}

// The instructions of a custom program, as they were given when it began, which the lead follows in all that it does there
export function InstructionsDialog({ name, instructions, onClose }: { name: string; instructions: string; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl" data-testid="program-instructions">
        <DialogHeader>
          <DialogTitle>Instructions of {name || "this program"}</DialogTitle>
          <DialogDescription>
            The lead follows these in all that it does in this program, and for every message. They stay as they were when it began.
          </DialogDescription>
        </DialogHeader>
        <div
          role="region"
          aria-label="Instructions"
          tabIndex={0}
          className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-muted/60 px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {instructions}
        </div>
      </DialogContent>
    </Dialog>
  );
}
