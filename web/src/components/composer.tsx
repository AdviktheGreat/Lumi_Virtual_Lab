"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ComposerProps {
  value: string;
  onValueChange: (value: string) => void;
  // Sends what is written. The draft is the parent's to clear, once what it was sent for has been done
  onSend: () => void;
  // Whether the lead is at work, where the way to send is the way to stop it instead
  running?: boolean;
  onStop?: () => void;
  // Whether a message is being sent, or cannot be
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  // What goes beside the button
  footer?: React.ReactNode;
  className?: string;
}

export function Composer({
  value,
  onValueChange,
  onSend,
  running = false,
  onStop,
  disabled = false,
  placeholder = "Ask the lead scientist…",
  autoFocus = false,
  footer,
  className,
}: ComposerProps) {
  const input = useRef<HTMLTextAreaElement>(null);
  const empty = value.trim() === "";

  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);

  // The box is as tall as what is in it, up to its limit, in browsers that cannot do that by themselves
  useLayoutEffect(() => {
    const box = input.current;
    if (box === null) return;
    box.style.height = "auto";
    box.style.height = `${box.scrollHeight}px`;
  }, [value]);

  return (
    <form
      className={cn(
        "flex flex-col gap-2 rounded-2xl border border-input bg-card p-2.5 shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/25",
        className,
      )}
      onSubmit={(event) => {
        event.preventDefault();
        if (!empty && !disabled && !running) onSend();
      }}
    >
      <textarea
        ref={input}
        aria-label="Message"
        rows={1}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={(event) => {
          // Enter that picks a character of an input method is not a message
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        className="max-h-60 min-h-11 w-full resize-none bg-transparent px-1.5 py-1 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
      />
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{footer}</div>
        {running ? (
          <Button type="button" size="icon" aria-label="Stop" onClick={onStop} className="rounded-full">
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button type="submit" size="icon" aria-label="Send" disabled={empty || disabled} className="rounded-full">
            <ArrowUp className="size-4" />
          </Button>
        )}
      </div>
    </form>
  );
}
