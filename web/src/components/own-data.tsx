"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Eye, EyeOff, File as FileIcon, Folder, Pencil, Plus, Trash2, X } from "lucide-react";
import { Aside, describedBy, Field, Section } from "@/components/settings-fields";
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
import { Progress } from "@/components/ui/progress";
import { Radio } from "@/components/ui/radio";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatBytes } from "@/lib/files";
import {
  checkData,
  dataFacts,
  descriptionProblem,
  EMPTY_DATA,
  MAX_DESCRIPTION,
  type DataDraft,
  type Way,
} from "@/lib/own";
import { tidy } from "@/lib/scientists";
import type { Own, OwnData, OwnPreview } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

// Says what the change was, and what the data is as it now is
type Changed = (own: Own, said: string) => void;

function PreviewPanel({ id, name }: { id: string; name: string }) {
  const { report } = useServer();
  const [preview, setPreview] = useState<Loaded<OwnPreview>>({ kind: "loading" });

  useEffect(() => {
    const abort = new AbortController();
    api.previewOwnData(name, abort.signal).then(
      (value) => setPreview({ kind: "ready", value }),
      (error: unknown) => {
        if (abort.signal.aborted) return;
        report(error);
        setPreview({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, [name, report]);

  if (preview.kind === "loading") {
    return (
      <p id={id} role="status" className="text-xs text-muted-foreground">
        Looking at {name}…
      </p>
    );
  }
  if (preview.kind === "failed") {
    return (
      <p id={id} role="alert" className="text-xs text-destructive">
        {describeError(preview.error)}
      </p>
    );
  }

  const shown = preview.value;

  return (
    <div id={id} className="flex flex-col gap-1.5">
      {shown.kind === "text" && (
        <>
          {shown.lines.length === 0 ? (
            <p className="text-xs text-muted-foreground">The file is empty.</p>
          ) : (
            <div role="region" aria-label={`The start of ${name}`} tabIndex={0} className="max-h-64 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <pre className="font-mono text-xs leading-5">{shown.lines.join("\n")}</pre>
            </div>
          )}
          {shown.truncated && <p className="text-xs text-muted-foreground">Only the start of it is shown.</p>}
        </>
      )}
      {shown.kind === "binary" && (
        <p className="text-xs text-muted-foreground">This is not a text file, so there is nothing of it to show.</p>
      )}
      {shown.kind === "folder" && (
        <>
          {shown.entries.length === 0 ? (
            <p className="text-xs text-muted-foreground">The folder is empty.</p>
          ) : (
            <ul aria-label={`In ${name}`} className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
              {shown.entries.map((entry) => (
                <li key={entry.name} className="flex min-w-0 items-center gap-1.5">
                  {entry.folder ? (
                    <Folder aria-hidden className="size-3 shrink-0 text-muted-foreground" />
                  ) : (
                    <FileIcon aria-hidden className="size-3 shrink-0 text-muted-foreground" />
                  )}
                  <span className="truncate">{entry.name}</span>
                  <span className="sr-only">{entry.folder ? "folder" : "file"}</span>
                </li>
              ))}
            </ul>
          )}
          {shown.more > 0 && <p className="text-xs text-muted-foreground">And {shown.more} more.</p>}
        </>
      )}
      {shown.kind === "missing" && <p className="text-xs text-muted-foreground">It is not there any more.</p>}
    </div>
  );
}

function DescriptionForm({
  data,
  onSaved,
  onCancel,
}: {
  data: OwnData;
  onSaved: Changed;
  onCancel: () => void;
}) {
  const { report } = useServer();
  const id = useId();
  const [text, setText] = useState(data.description);
  const [tried, setTried] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const wrong = descriptionProblem(text, "it");
  const shown = tried ? wrong : null;

  async function save() {
    setTried(true);
    if (wrong !== null) return;
    setSaving(true);
    setProblem(null);
    try {
      onSaved(await api.describeOwnData(data.name, tidy(text)), `Saved what ${data.name} is.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
      setSaving(false);
    }
  }

  return (
    <form
      aria-label={`What ${data.name} is`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-2"
    >
      <Field id={id} label="What it is" problem={shown ?? undefined}>
        <Textarea
          id={id}
          value={text}
          onChange={(event) => setText(event.target.value)}
          readOnly={saving}
          rows={3}
          autoFocus
          aria-invalid={shown !== null}
          aria-describedby={describedBy(id, { problem: shown !== null })}
        />
      </Field>
      {problem && (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving}>
          Save
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function DataRow({
  data,
  onChanged,
  onRemove,
}: {
  data: OwnData;
  onChanged: Changed;
  onRemove: (button: HTMLButtonElement) => void;
}) {
  const previewId = useId();
  const [previewing, setPreviewing] = useState(false);
  const [editing, setEditing] = useState(false);
  const missing = data.kind === "missing";
  // What is not there cannot be looked into, so a look that was asked for is not shown once it has gone
  const open = previewing && !missing;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="own-data">
      <div className="flex items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <code className="break-all text-sm font-medium">{data.name}</code>
          <p className="text-xs text-muted-foreground">{dataFacts(data)}</p>
          {data.path !== null && (
            <p className="break-all text-xs text-muted-foreground">
              Kept where it is, in <code>{data.path}</code>
            </p>
          )}
          {editing ? (
            <DescriptionForm
              data={data}
              onSaved={(own, said) => {
                setEditing(false);
                onChanged(own, said);
              }}
              onCancel={() => setEditing(false)}
            />
          ) : (
            <p className="text-sm">{data.description}</p>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setPreviewing((was) => !was)}
          disabled={missing}
          aria-expanded={open}
          aria-controls={open ? previewId : undefined}
          aria-label={`${open ? "Hide" : "Show"} the start of ${data.name}`}
        >
          {open ? <EyeOff /> : <Eye />}
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setEditing(true)}
          disabled={editing}
          aria-label={`Change what ${data.name} is`}
        >
          <Pencil />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={(event) => onRemove(event.currentTarget)}
          aria-label={`Delete ${data.name}`}
        >
          <Trash2 />
        </Button>
      </div>
      {missing && (
        <Aside tone="warning">
          It is not there any more, so conversations are not given it. Put it back where it was, or delete it here.
        </Aside>
      )}
      {open && <PreviewPanel id={previewId} name={data.name} />}
    </li>
  );
}

function AddData({ own, onAdded, submit }: { own: Own; onAdded: Changed; submit: React.Ref<HTMLButtonElement> }) {
  const { report } = useServer();
  const id = useId();
  const [draft, setDraft] = useState<DataDraft>(EMPTY_DATA);
  const [tried, setTried] = useState(false);
  const [working, setWorking] = useState(false);
  const [progress, setProgress] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  // A file chosen cannot be taken out of its input, so the input is made again to empty it
  const [inputs, setInputs] = useState(0);
  const sending = useRef<AbortController | null>(null);

  useEffect(() => () => sending.current?.abort(), []);

  const problems = checkData(draft, own.data.map((data) => data.name), own.max_upload_bytes);
  // A file that was chosen is looked at as it is, since choosing it was the act that it is checked for
  const source = tried || (draft.way === "upload" && draft.file !== null) ? problems.source : undefined;
  const description = tried ? problems.description : undefined;
  const sourceId = `${id}-source`;
  const descriptionId = `${id}-description`;

  function change(part: Partial<DataDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function add() {
    setTried(true);
    if (Object.keys(problems).length > 0) return;
    const controller = new AbortController();
    sending.current = controller;
    setWorking(true);
    setProgress(0);
    setProblem(null);
    try {
      const said = tidy(draft.description);
      const given =
        draft.way === "upload" && draft.file !== null
          ? await api.uploadOwnData(draft.file, said, { onProgress: setProgress, signal: controller.signal })
          : await api.addOwnPath(draft.path.trim(), said);
      const added = given.data.find((data) => !own.data.some((was) => was.name === data.name));
      setDraft({ ...EMPTY_DATA, way: draft.way });
      setInputs((was) => was + 1);
      setTried(false);
      onAdded(given, added === undefined ? "Added the data." : `Added ${added.name}.`);
    } catch (error) {
      // A file that was called off is not a failure to say anything of
      if (!controller.signal.aborted) {
        report(error);
        setProblem(describeError(error));
      }
    } finally {
      sending.current = null;
      setWorking(false);
    }
  }

  return (
    <form
      aria-label="Give the lab some data"
      onSubmit={(event) => {
        event.preventDefault();
        void add();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2" disabled={working}>
        <legend className="mb-1.5 text-sm font-medium">Give it by</legend>
        {(
          [
            ["upload", "Uploading a file"],
            ["path", "Pointing to a file or folder on this machine"],
          ] satisfies [Way, string][]
        ).map(([way, label]) => (
          <label key={way} className="flex items-center gap-2 text-sm">
            <Radio name={`${id}-way`} checked={draft.way === way} onChange={() => change({ way })} />
            {label}
          </label>
        ))}
      </fieldset>

      {draft.way === "upload" ? (
        <Field
          id={sourceId}
          label="File"
          hint={`Up to ${formatBytes(own.max_upload_bytes)}. The lab keeps its own copy. For a bigger file, or a folder, point to it where it is.`}
          problem={source}
        >
          <Input
            key={inputs}
            id={sourceId}
            type="file"
            onChange={(event) => change({ file: event.target.files?.[0] ?? null })}
            disabled={working}
            aria-invalid={source !== undefined}
            aria-describedby={describedBy(sourceId, { hint: true, problem: source !== undefined })}
            className="h-auto cursor-pointer py-1 file:mr-3 file:cursor-pointer file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground"
          />
        </Field>
      ) : (
        <Field
          id={sourceId}
          label="Full path"
          hint="Where it is on the machine the lab runs on. It is left there, and not copied or changed. Code is given it to read."
          problem={source}
        >
          <Input
            id={sourceId}
            value={draft.path}
            onChange={(event) => change({ path: event.target.value })}
            placeholder="/Users/you/data/counts.csv"
            readOnly={working}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={source !== undefined}
            aria-describedby={describedBy(sourceId, { hint: true, problem: source !== undefined })}
          />
        </Field>
      )}

      <Field
        id={descriptionId}
        label="What it is"
        hint="What is in it and how it is laid out, which is what the lead reads to know when to use it."
        problem={description}
      >
        <Textarea
          id={descriptionId}
          value={draft.description}
          onChange={(event) => change({ description: event.target.value })}
          rows={3}
          readOnly={working}
          maxLength={MAX_DESCRIPTION * 4}
          aria-invalid={description !== undefined}
          aria-describedby={describedBy(descriptionId, { hint: true, problem: description !== undefined })}
        />
      </Field>

      {working && draft.way === "upload" && draft.file !== null && (
        <div className="flex flex-col gap-1" role="status">
          <Progress value={progress} aria-label={`Uploading ${draft.file.name}`} />
          <p className="text-xs text-muted-foreground">
            Uploading {draft.file.name}, {Math.round(progress * 100)}%
          </p>
        </div>
      )}
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <div className="flex gap-2">
        <Button ref={submit} type="submit" disabled={working}>
          <Plus />
          {working ? "Adding…" : "Add the data"}
        </Button>
        {working && draft.way === "upload" && (
          <Button type="button" variant="outline" onClick={() => sending.current?.abort()}>
            <X />
            Cancel the upload
          </Button>
        )}
      </div>
    </form>
  );
}

// What the person gave the lab as data: what it is, where it is, what is in it, and the giving of more
export function OwnDataSection({ own, onChanged }: { own: Own; onChanged: Changed }) {
  const { report } = useServer();
  // The one asked about stays set after the question is closed, so that it is not blanked while it fades
  const [removing, setRemoving] = useState<OwnData | null>(null);
  const [asking, setAsking] = useState(false);
  const asker = useRef<HTMLButtonElement | null>(null);
  const adder = useRef<HTMLButtonElement | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  function changed(next: Own, said: string) {
    setProblem(null);
    setDone(said);
    onChanged(next, said);
  }

  async function remove(data: OwnData) {
    setProblem(null);
    setDone(null);
    try {
      changed(await api.removeOwnData(data.name), `Deleted ${data.name}.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {own.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">You have not given the lab any data yet.</p>
      ) : (
        <ul aria-label="Your data" className="flex flex-col gap-2">
          {own.data.map((data) => (
            <DataRow
              key={data.name}
              data={data}
              onChanged={changed}
              onRemove={(button) => {
                asker.current = button;
                setRemoving(data);
                setAsking(true);
              }}
            />
          ))}
        </ul>
      )}
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      {done && (
        <p role="status" className="text-xs text-muted-foreground">
          {done}
        </p>
      )}
      <Section title="Add data">
        <AddData own={own} onAdded={changed} submit={adder} />
      </Section>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            // Nothing opened the question but a button of the list, which is gone when its data was deleted
            event.preventDefault();
            const back = asker.current?.isConnected ? asker.current : adder.current;
            back?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {removing?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {removing?.source === "uploaded"
                ? "This deletes the copy of it that the lab keeps. Conversations you start from now on are not given it."
                : `The lab stops being given it. What is at ${removing?.path ?? "its path"} is left where it is.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (removing !== null) void remove(removing);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
