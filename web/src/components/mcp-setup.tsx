"use client";

import { useId, useRef, useState } from "react";
import { KeyForm } from "@/components/settings-keys";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { Radio } from "@/components/ui/radio";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { describeCheck, describeSignIn, keysToGive, keysToSetElsewhere } from "@/lib/mcp";
import type { McpChange, McpCheck, McpServer } from "@/lib/types";
import { cn } from "@/lib/utils";

// What looking at a server, by connecting to it, has come to
type Check = { kind: "idle" } | { kind: "checking" } | { kind: "found"; check: McpCheck } | { kind: "failed"; problem: string };

function CheckResult({ check }: { check: Check }) {
  if (check.kind === "checking") {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Connecting…
      </p>
    );
  }
  if (check.kind === "failed") {
    return (
      <p role="alert" className="text-xs text-destructive">
        {check.problem}
      </p>
    );
  }
  if (check.kind === "idle") return null;
  const { text, tools, more } = describeCheck(check.check);
  if (!check.check.ok) {
    return (
      <p role="alert" className="text-xs whitespace-pre-wrap break-words text-destructive">
        {text}
      </p>
    );
  }

  return (
    <p role="status" className="text-xs break-words text-muted-foreground">
      {text}
      {tools.map((tool, at) => (
        <span key={tool}>
          {at === 0 ? " " : ", "}
          <code>{tool}</code>
        </span>
      ))}
      {more > 0 && ` and ${more} more`}
    </p>
  );
}

// What it takes for a server to be used, and what can be done about it: how it is signed in to or given a key, the keys it
// asks for, why it cannot work if it cannot, whether it is signed in to, a look at whether it can be connected to, and how
// to set it up. A change to the server takes what a look found away, since that is of the server as it was.
export function ServerSetup({
  server,
  onChange,
  onKeysChanged,
  onSignOut,
  inset = false,
}: {
  server: McpServer;
  onChange: (change: McpChange) => void;
  onKeysChanged: () => void;
  onSignOut: () => void;
  // Whether it is set in from the left, to be under the box of a server that is on or off
  inset?: boolean;
}) {
  const { report } = useServer();
  const id = useId();
  const elsewhere = keysToSetElsewhere(server);
  const keys = keysToGive(server);
  const signIn = describeSignIn(server);
  const [check, setCheck] = useState<Check>({ kind: "idle" });
  // Which check is the latest, so that what an earlier one found, after the server was changed, is not shown
  const latest = useRef(0);
  const indent = inset ? "pl-6.5" : undefined;

  function forget() {
    latest.current += 1;
    setCheck({ kind: "idle" });
  }

  async function look() {
    latest.current += 1;
    const mine = latest.current;
    setCheck({ kind: "checking" });
    try {
      const found = await api.checkMcpServer(server.name);
      if (mine === latest.current) setCheck({ kind: "found", check: found });
    } catch (error) {
      report(error);
      if (mine === latest.current) setCheck({ kind: "failed", problem: describeError(error) });
    }
  }

  return (
    <>
      {server.auth_choices.length > 0 && (
        <fieldset className={cn("flex flex-col gap-1.5", indent)}>
          <legend className="pb-1 text-xs font-medium text-muted-foreground">How it is signed in to</legend>
          <label className="flex items-center gap-2 text-sm">
            <Radio
              name={`${id}-auth`}
              checked={server.auth === "key"}
              onChange={() => {
                forget();
                onChange({ auth: "key" });
              }}
            />
            An API key
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Radio
              name={`${id}-auth`}
              checked={server.auth === "oauth"}
              onChange={() => {
                forget();
                onChange({ auth: "oauth" });
              }}
            />
            Your account, signed in to in the browser
          </label>
        </fieldset>
      )}

      {keys.length > 0 && (
        <div className={cn("flex flex-col gap-2", indent)}>
          {keys.map((key) => (
            <KeyForm
              key={key.name}
              row={{ name: key.name, provider: server.title, set: key.set, source: null }}
              onChanged={() => {
                forget();
                onKeysChanged();
              }}
            />
          ))}
        </div>
      )}

      {elsewhere.length > 0 && (
        <p className={cn("text-xs text-muted-foreground", indent)}>
          It needs {elsewhere.map((name, at) => (
            <span key={name}>
              {at > 0 && ", "}
              <code>{name}</code>
            </span>
          ))}
          , which this page cannot give: set {elsewhere.length === 1 ? "it" : "them"} where the server was started, and start it again.
        </p>
      )}

      {server.problem !== null && (
        <p role="alert" className={cn("text-xs text-destructive", indent)}>
          {server.problem}
        </p>
      )}

      {signIn !== null && (
        <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground", indent)}>
          <span data-testid={`mcp-${server.name}-sign-in`}>{signIn}</span>
          {server.signed_in && (
            <Button
              type="button"
              variant="outline"
              size="xs"
              aria-label={`Sign out of ${server.title}`}
              onClick={() => {
                forget();
                onSignOut();
              }}
            >
              Sign out
            </Button>
          )}
        </div>
      )}

      {server.missing.length === 0 && (
        <div className={cn("flex flex-col items-start gap-1.5", indent)}>
          <Button type="button" variant="outline" size="xs" disabled={check.kind === "checking"} onClick={() => void look()}>
            Check connection<span className="sr-only"> to {server.title}</span>
          </Button>
          <CheckResult check={check} />
        </div>
      )}

      {server.setup !== null && (
        <details className={cn("text-xs text-muted-foreground", indent)}>
          <summary className="cursor-pointer rounded outline-none focus-visible:ring-3 focus-visible:ring-ring/50">How to set it up</summary>
          <p className="mt-1.5 whitespace-pre-wrap break-words">{server.setup}</p>
        </details>
      )}
    </>
  );
}
