"use client";

import { useId, useState } from "react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { describeAnchor } from "@/lib/paperagents";
import type { PaperAgentPassage, ReadAnchor } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// How many characters of a quote are said in the name of the button that shows where it is
const NAME_CHARS = 60;

// The words of the paper at a place, with what is around them, and the words of the fact marked
function Passage({ id, passage }: { id: string; passage: PaperAgentPassage }) {
  return (
    <div id={id} role="group" aria-label="The paper at this place" className="whitespace-pre-wrap break-words rounded-md bg-muted/40 p-2 text-xs leading-relaxed">
      <span className="text-muted-foreground">{passage.before}</span>
      <mark className="rounded-sm bg-primary/20 px-0.5 text-foreground">{passage.text}</mark>
      <span className="text-muted-foreground">{passage.after}</span>
    </div>
  );
}

// Where in the paper the words of a fact are, in words, and the way to see them in the paper
export function Place({ agent, quote, anchor }: { agent: string; quote: string; anchor: ReadAnchor }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [passage, setPassage] = useState<PaperAgentPassage | null>(null);
  const excerpt = quote.length > NAME_CHARS ? `${quote.slice(0, NAME_CHARS)}…` : quote;

  async function toggle() {
    if (passage !== null) {
      setPassage(null);

      return;
    }
    const found = await attempt.run(() => api.paperAgentPassage(agent, anchor.start, anchor.end));
    if (found) setPassage(found);
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">{describeAnchor(anchor)}</span>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => void toggle()}
          disabled={attempt.busy}
          aria-expanded={passage !== null}
          aria-controls={passage !== null ? `${id}-passage` : undefined}
          aria-label={`${passage !== null ? "Hide" : "Show in the paper"}: ${excerpt}`}
        >
          {passage !== null ? "Hide" : attempt.busy ? "Looking…" : "Show in the paper"}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      {passage !== null && <Passage id={`${id}-passage`} passage={passage} />}
    </>
  );
}
