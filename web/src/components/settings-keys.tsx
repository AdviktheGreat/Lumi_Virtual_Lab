"use client";

import { useState } from "react";
import { Check, KeyRound } from "lucide-react";
import { Aside, Section } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { keyProblem, keyRows, type KeyRow } from "@/lib/keys";
import type { KeyStatuses } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

export function KeyForm({ row, onChanged }: { row: KeyRow; onChanged: (statuses: KeyStatuses) => void }) {
  const { report } = useServer();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const id = `settings-key-${row.name}`;

  async function change(action: "save" | "remove") {
    if (action === "save") {
      const wrong = keyProblem(typed);
      if (wrong !== null) {
        setProblem(wrong);

        return;
      }
    }
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      const statuses = action === "save" ? await api.setKey(row.name, typed.trim()) : await api.removeKey(row.name);
      // The key is not kept here once the server has it
      setTyped("");
      setDone(action === "save" ? "Saved" : "Removed");
      onChanged(statuses);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void change("save");
      }}
      className="flex flex-col gap-2 rounded-lg border border-border p-3"
    >
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {row.provider} key
        </label>
        <code className="text-xs text-muted-foreground">{row.name}</code>
        <Badge variant={row.set ? "secondary" : "outline"} className="ml-auto" data-testid={`key-state-${row.name}`}>
          {row.set ? "Set" : "Not set"}
        </Badge>
      </div>
      <div className="flex gap-2">
        <Input
          id={id}
          type="password"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            setProblem(null);
            setDone(null);
          }}
          placeholder={row.set ? "Paste another to replace it" : "Paste the key"}
          aria-invalid={problem !== null}
          aria-describedby={problem !== null ? `${id}-problem` : undefined}
          // A key is a secret, which a browser would offer to remember and a password manager to fill
          autoComplete="off"
          spellCheck={false}
          data-1p-ignore
          data-lpignore="true"
          readOnly={busy}
        />
        <Button type="submit" variant="outline" disabled={busy || typed.trim() === ""}>
          Save
        </Button>
        {row.set && (
          <Button type="button" variant="ghost" disabled={busy} onClick={() => void change("remove")} aria-label={`Remove the ${row.provider} key`}>
            Remove
          </Button>
        )}
      </div>
      {problem && (
        <p id={`${id}-problem`} role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
      {done && (
        <p role="status" className="flex items-center gap-1 text-xs text-muted-foreground">
          <Check className="size-3" aria-hidden />
          {done}
        </p>
      )}
    </form>
  );
}

export function KeysTab({ keys, onChanged }: { keys: Loaded<KeyStatuses>; onChanged: (statuses: KeyStatuses) => void }) {
  return (
    <Section title="API keys">
      <Aside>
        <KeyRound className="mr-1.5 inline size-3.5 align-text-bottom" aria-hidden />
        A key you give here is kept by the server until it stops. It is not written to disk and is never shown again. A key the
        server was started with can be taken away here, and is back when the server is started again.
      </Aside>
      {keys.kind === "loading" && <p className="text-sm text-muted-foreground">Looking at which keys are set…</p>}
      {keys.kind === "failed" && <p role="alert" className="text-sm text-destructive">{describeError(keys.error)}</p>}
      {keys.kind === "ready" && (
        <div className="flex flex-col gap-3">
          {keyRows(keys.value).map((row) => (
            <KeyForm key={row.name} row={row} onChanged={onChanged} />
          ))}
        </div>
      )}
    </Section>
  );
}
