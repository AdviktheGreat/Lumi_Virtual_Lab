"use client";

import { useState } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { common, createLowlight } from "lowlight";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/copy-button";
import { languageLabel } from "@/lib/calls";
import { fold } from "@/lib/fold";
import { cn } from "@/lib/utils";

const lowlight = createLowlight(common);

// Code longer than this is shown as it is: colouring it would make the page slow for little
const HIGHLIGHT_CHARS = 30_000;

// Code with its parts told apart by colour, where its language is one that is known
export function Highlighted({ code, language }: { code: string; language: string | null }) {
  if (language !== null && code.length <= HIGHLIGHT_CHARS && lowlight.registered(language)) {
    return toJsxRuntime(lowlight.highlight(language, code), { Fragment, jsx, jsxs });
  }

  return <>{code}</>;
}

interface CodeBlockProps {
  code: string;
  language: string | null;
  // How many lines are shown before the rest is folded away, which is all of them if not given
  foldAfter?: number;
  className?: string;
}

// Code, in a block of its own, with its language and a way to copy it
export function CodeBlock({ code, language, foldAfter, className }: CodeBlockProps) {
  const [open, setOpen] = useState(false);
  const folding = fold(code, foldAfter, open);

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-muted/50", className)}>
      <div className="flex h-7 items-center justify-between border-b border-border/70 pl-3 pr-1 text-xs text-muted-foreground">
        <span>{language ? languageLabel(language) : "Code"}</span>
        <CopyButton text={code} label="Copy code" />
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-[13px] leading-5">
        <code>
          <Highlighted code={folding.text} language={language} />
        </code>
      </pre>
      {folding.foldable && (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          className="h-7 w-full rounded-none border-t border-border/70 text-muted-foreground"
        >
          {open ? "Show less" : `Show ${folding.hidden} more lines`}
        </Button>
      )}
    </div>
  );
}
