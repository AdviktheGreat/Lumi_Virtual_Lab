"use client";

import { useId, useRef, useState } from "react";
import { Download } from "lucide-react";
import { describedBy, Field } from "@/components/settings-fields";
import { PutInResult } from "@/components/skill-put-in-result";
import { useServer } from "@/components/server-provider";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { skillsFrom } from "@/lib/skills";
import type { SkillsFrom, SkillsPutIn } from "@/lib/types";

// Where skills are put in from: a Git repository, or a folder on this machine. Skills are instructions that the lead
// follows and scripts that code may run, so what is asked for is asked again before it is fetched.
export function SkillInstall({ onPutIn }: { onPutIn: (result: SkillsPutIn) => void }) {
  const { report } = useServer();
  const id = useId();
  const [text, setText] = useState("");
  const [tried, setTried] = useState(false);
  const [asking, setAsking] = useState(false);
  // What is asked about stays set after the question is closed, so that it is not blanked while it fades
  const [from, setFrom] = useState<SkillsFrom | null>(null);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<SkillsPutIn | null>(null);
  const submit = useRef<HTMLButtonElement | null>(null);
  const checked = skillsFrom(text);
  const wrong = tried && "problem" in checked ? checked.problem : undefined;
  const fieldId = `${id}-from`;

  function ask() {
    setTried(true);
    setResult(null);
    setProblem(null);
    if ("problem" in checked) return;
    setFrom(checked.from);
    setAsking(true);
  }

  async function putIn(source: SkillsFrom) {
    setWorking(true);
    setProblem(null);
    try {
      const done = await api.putInSkills(source);
      setResult(done);
      onPutIn(done);
      if (done.installed.length > 0) {
        setText("");
        setTried(false);
      }
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setWorking(false);
    }
  }

  const address = from !== null && "git" in from ? from.git : null;

  return (
    <div className="flex flex-col gap-3">
      <form
        aria-label="Put in skills"
        onSubmit={(event) => {
          event.preventDefault();
          ask();
        }}
        className="flex flex-col gap-3 rounded-lg border border-border p-3"
      >
        <Field
          id={fieldId}
          label="Put in skills from"
          hint={
            <>
              The address of a Git repository, such as <code>https://github.com/owner/skills</code>, or the full path of a
              folder on this machine. Every skill found in it is copied into the lab&apos;s own folder.
            </>
          }
          problem={wrong}
        >
          <Input
            id={fieldId}
            value={text}
            onChange={(event) => setText(event.target.value)}
            readOnly={working}
            autoComplete="off"
            spellCheck={false}
            placeholder="https://github.com/…  or  /Users/you/skills"
            aria-invalid={wrong !== undefined}
            aria-describedby={describedBy(fieldId, { hint: true, problem: wrong !== undefined })}
          />
        </Field>
        <div className="flex items-center gap-3">
          <Button ref={submit} type="submit" disabled={working}>
            <Download />
            {working ? "Putting them in…" : "Put in the skills"}
          </Button>
          {working && address !== null && (
            <p role="status" className="text-xs text-muted-foreground">
              Fetching the repository, which can take a minute.
            </p>
          )}
        </div>
      </form>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      {result !== null && <PutInResult result={result} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            submit.current?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Put in the skills of {address ?? "this folder"}?</AlertDialogTitle>
            <AlertDialogDescription>
              A skill is instructions that the lead follows, and it may come with scripts that code can run in a
              conversation. Put in only those you trust. They are copied, so a later change at{" "}
              {address === null ? "the folder" : "the repository"} is not picked up.
              {from !== null && "path" in from && <> The folder is {from.path}.</>}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (from !== null) void putIn(from);
              }}
            >
              Put them in
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
