"use client";

import { useEffect, useRef, useState } from "react";
import { Wrench } from "lucide-react";
import { Aside, Section } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { disabledWhen, groupTools, howManyOn } from "@/lib/tools";
import type { ToolInfo } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

// A button that cannot be used right now but keeps the focus it has, which a disabled one would not
const UNAVAILABLE = "aria-disabled:pointer-events-none aria-disabled:opacity-50";

// The library's tools, which the lead can call to look things up. Each is kept as it is chosen, as the keys and the
// scientists are, and a conversation is given the tools that are on when it begins.
export function ToolsTab({ tools, onChanged }: { tools: Loaded<ToolInfo[]>; onChanged: (tools: ToolInfo[]) => void }) {
  const { report } = useServer();
  const [problem, setProblem] = useState<string | null>(null);
  // What was chosen and is not yet kept, which is shown as it was chosen, so that a box answers at once. It is shown until
  // every change has been answered, and then what the server holds is what is shown, whether it kept them or not.
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  // The tools as the server last gave them, which each change is made to. Changes are made one after another, so that
  // two in quick succession do not each start from what was shown before the other, and the boxes stay usable (and keep
  // the focus) while one is being kept.
  const latest = useRef<ToolInfo[] | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);

  useEffect(() => {
    if (tools.kind === "ready" && waiting.current === 0) latest.current = tools.value;
  }, [tools]);

  function turn(names: string[], enabled: boolean) {
    waiting.current += 1;
    setChosen((was) => ({ ...was, ...Object.fromEntries(names.map((name) => [name, enabled])) }));
    queue.current = queue.current.then(async () => {
      try {
        if (latest.current === null) return;
        setProblem(null);
        const kept = await api.saveTools(disabledWhen(latest.current, names, enabled));
        latest.current = kept;
        onChanged(kept);
      } catch (error) {
        report(error);
        setProblem(describeError(error));
      } finally {
        waiting.current -= 1;
        if (waiting.current === 0) setChosen({});
      }
    });
  }

  const shown =
    tools.kind === "ready" ? tools.value.map((tool) => (tool.name in chosen ? { ...tool, enabled: chosen[tool.name] } : tool)) : [];

  return (
    <Section title="Tools">
      <Aside>
        <Wrench className="mr-1.5 inline size-3.5 align-text-bottom" aria-hidden />
        The lead can call these to look things up in public literature and databases, and to read the files you attach. Each
        call is shown in the conversation as it is made. A conversation is given the tools that are on when it begins, and
        every one adds to what each message costs, since the model is told what it does.
      </Aside>
      {tools.kind === "loading" && <p className="text-sm text-muted-foreground">Looking at the tools…</p>}
      {tools.kind === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {describeError(tools.error)}
        </p>
      )}
      {tools.kind === "ready" && (
        <>
          <div className="flex items-center gap-2">
            <p role="status" className="text-sm text-muted-foreground" data-testid="tools-count">
              {howManyOn(shown)}
            </p>
            <Button
              variant="outline"
              size="sm"
              className={`ml-auto ${UNAVAILABLE}`}
              aria-disabled={shown.every((tool) => tool.enabled)}
              onClick={() => {
                if (!shown.every((tool) => tool.enabled)) turn(shown.map((tool) => tool.name), true);
              }}
            >
              Turn all on
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={UNAVAILABLE}
              aria-disabled={shown.every((tool) => !tool.enabled)}
              onClick={() => {
                if (!shown.every((tool) => !tool.enabled)) turn(shown.map((tool) => tool.name), false);
              }}
            >
              Turn all off
            </Button>
          </div>
          {problem && (
            <p role="alert" className="text-xs text-destructive">
              {problem}
            </p>
          )}
          <div className="flex flex-col gap-5">
            {groupTools(shown).map((group) => (
              <fieldset key={group.name} className="flex min-w-0 flex-col gap-2">
                <legend className="pb-1 text-sm font-medium">{group.name}</legend>
                {group.tools.map((tool) => (
                  <label key={tool.name} className="flex items-start gap-2.5 text-sm">
                    <Checkbox
                      checked={tool.enabled}
                      onChange={(event) => turn([tool.name], event.target.checked)}
                      className="mt-0.5"
                    />
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="flex items-center gap-2">
                        <code className="text-[13px]">{tool.name}</code>
                        {tool.needs_code && <Badge variant="outline">Needs code</Badge>}
                      </span>
                      <span className="text-xs text-muted-foreground">{tool.summary}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
        </>
      )}
    </Section>
  );
}
