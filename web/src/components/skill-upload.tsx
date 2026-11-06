"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import { FolderUp, TriangleAlert, Upload, X } from "lucide-react";
import { PutInResult } from "@/components/skill-put-in-result";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import {
  folderFromDrop,
  folderFromInput,
  folderProblem,
  folderSize,
  skillsIn,
  type DroppedEntry,
  type Picked,
  type PickedFolder,
  type FoundSkill,
} from "@/lib/skill-folder";
import type { SkillInfo, SkillsPutIn } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Chosen {
  folder: PickedFolder;
  skills: FoundSkill[];
  more: number;
}

function hasFiles(dataTransfer: DataTransfer | null): boolean {
  return dataTransfer !== null && Array.from(dataTransfer.types).includes("Files");
}

// What a drop holds, which is only there while the drop is being handled, so it is taken before anything is waited for
function droppedEntries(dataTransfer: DataTransfer): DroppedEntry[] | null {
  const items = Array.from(dataTransfer.items).filter((item) => item.kind === "file");
  if (items.length > 0 && typeof items[0].webkitGetAsEntry !== "function") return null;

  return items.flatMap((item) => {
    const entry = item.webkitGetAsEntry();

    return entry === null ? [] : [entry as unknown as DroppedEntry];
  });
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function Found({ chosen, have }: { chosen: Chosen; have: Set<string> }) {
  return (
    <ul aria-label="Skills in the folder" className="flex max-h-56 flex-col gap-2 overflow-y-auto">
      {chosen.skills.map((skill) => {
        const note = have.has(skill.name.toLowerCase())
          ? "You already have a skill with this name, so this one is left out. Delete the one you have to put this in."
          : skill.description === null
            ? "No description was found at the top of its SKILL.md. Without one the lead cannot tell when to use it, so it may be left out."
            : null;

        return (
          <li key={skill.path} className="flex flex-col gap-0.5 text-sm">
            <span className="break-words">
              <code className="font-medium">{skill.name}</code>
              {chosen.skills.length > 1 && <span className="ml-2 text-xs text-muted-foreground">{skill.path}</span>}
            </span>
            {skill.description !== null && <span className="line-clamp-2 break-words text-xs text-muted-foreground">{skill.description}</span>}
            {note !== null && (
              <span className="flex items-start gap-1 text-xs text-warning">
                <TriangleAlert className="mt-px size-3 shrink-0" aria-hidden />
                {note}
              </span>
            )}
          </li>
        );
      })}
      {chosen.more > 0 && <li className="text-xs text-muted-foreground">and {chosen.more} more, which are not listed</li>}
    </ul>
  );
}

function UploadBody({
  skills,
  onPutIn,
  onBusy,
  onClose,
}: {
  skills: SkillInfo[];
  onPutIn: (result: SkillsPutIn) => void;
  onBusy: (busy: boolean) => void;
  onClose: () => void;
}) {
  const { report } = useServer();
  const [chosen, setChosen] = useState<Chosen | null>(null);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [working, setWorking] = useState(false);
  const [progress, setProgress] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<SkillsPutIn | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const send = useRef<HTMLButtonElement | null>(null);
  const done = useRef<HTMLButtonElement | null>(null);
  const sending = useRef<AbortController | null>(null);
  // Which choice is the latest, so that a folder that was slow to read does not replace one that was chosen after it
  const latest = useRef(0);

  useEffect(() => () => sending.current?.abort(), []);
  useEffect(() => {
    if (chosen !== null) send.current?.focus();
  }, [chosen]);
  useEffect(() => {
    if (result !== null) done.current?.focus();
  }, [result]);

  const have = new Set(skills.filter((skill) => skill.source === "workspace").map((skill) => skill.name.toLowerCase()));
  const wrong = chosen === null ? null : folderProblem(chosen.folder);

  async function take(picking: Picked | Promise<Picked>) {
    const mine = ++latest.current;
    setReading(true);
    setProblem(null);
    setResult(null);
    const picked = await picking;
    if (mine !== latest.current) return;
    if ("problem" in picked) {
      setChosen(null);
      setProblem(picked.problem);
      setReading(false);

      return;
    }
    // A folder is looked in only as far as is shown, and a file that cannot be read now is a skill that is not listed
    const found = await skillsIn(picked.folder).catch(() => ({ skills: [], more: 0 }));
    if (mine !== latest.current) return;
    setChosen({ folder: picked.folder, ...found });
    setReading(false);
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    if (working || !hasFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragging(false);
    const entries = droppedEntries(event.dataTransfer);
    void take(
      entries === null
        ? { problem: "This browser cannot read a folder that is dropped. Choose it instead." }
        : folderFromDrop(entries),
    );
  }

  async function upload() {
    if (chosen === null || wrong !== null) return;
    const controller = new AbortController();
    sending.current = controller;
    setWorking(true);
    onBusy(true);
    setProgress(0);
    setProblem(null);
    try {
      const put = await api.uploadSkillFolder(chosen.folder, { onProgress: setProgress, signal: controller.signal });
      setChosen(null);
      setResult(put);
      onPutIn(put);
    } catch (error) {
      // An upload that was called off is not a failure to say anything of
      if (!controller.signal.aborted) {
        report(error);
        setProblem(describeError(error));
      }
    } finally {
      sending.current = null;
      setWorking(false);
      onBusy(false);
    }
  }

  if (result !== null) {
    return (
      <>
        <div className="flex flex-col gap-3">
          <PutInResult result={result} />
          {result.installed.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {result.installed.map((skill) => skill.name).join(", ")} {result.installed.length === 1 ? "is" : "are"} now with the
              lab&apos;s skills, and on, so the next conversation is given {result.installed.length === 1 ? "it" : "them"}.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setResult(null)}>
            Upload another
          </Button>
          <Button ref={done} type="button" onClick={onClose}>
            Done
          </Button>
        </DialogFooter>
      </>
    );
  }

  return (
    <>
      <div
        data-testid="skill-folder-zone"
        data-dragging={dragging}
        className={cn(
          "flex flex-col gap-3 rounded-xl border border-dashed border-input p-4 transition-colors data-[dragging=true]:border-brand data-[dragging=true]:bg-brand/5",
          chosen !== null && "border-solid",
        )}
        onDragOver={(event) => {
          if (working || !hasFiles(event.dataTransfer)) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={drop}
      >
        {/* A folder is chosen with an input that takes one, which is not shown: the button beside it opens it */}
        <input
          ref={input}
          type="file"
          aria-label="Skill folder"
          className="sr-only"
          tabIndex={-1}
          {...{ webkitdirectory: "" }}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            // Nothing is chosen when the browser's own window is closed, which is not a folder with nothing in it
            if (files.length > 0) void take(folderFromInput(files));
          }}
        />
        {chosen === null ? (
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <FolderUp className="size-8 text-muted-foreground" aria-hidden />
            <p className="text-sm font-medium">{reading ? "Looking in the folder…" : "Drop a skill folder here"}</p>
            <p className="max-w-sm text-xs text-muted-foreground">
              A skill is a folder with a SKILL.md in it, which says at its top what the skill is called and what it is for. The
              scripts and other files in the folder come with it.
            </p>
            <Button type="button" variant="outline" disabled={reading} onClick={() => input.current?.click()}>
              Choose a folder
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="break-words font-medium" data-testid="skill-folder-name">
                  {chosen.folder.name}
                </p>
                <p className="text-xs text-muted-foreground">
                  {plural(chosen.folder.files.length, "file")}, {folderSize(chosen.folder.bytes)}
                  {chosen.folder.passedOver > 0 && <>. {chosen.folder.passedOver} left out that a skill does not need, such as .git folders and .DS_Store files</>}
                </p>
              </div>
              <Button type="button" variant="ghost" size="sm" disabled={working || reading} onClick={() => input.current?.click()}>
                Choose another
              </Button>
            </div>
            {wrong === null && chosen.skills.length > 0 && (
              <>
                <p className="text-xs font-medium text-muted-foreground">{plural(chosen.skills.length + chosen.more, "skill")} in it</p>
                <Found chosen={chosen} have={have} />
              </>
            )}
          </div>
        )}
      </div>
      {wrong !== null && (
        <p role="alert" className="text-sm text-destructive">
          {wrong}
        </p>
      )}
      {problem !== null && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      {working && chosen !== null && (
        <div className="flex flex-col gap-1" role="status">
          <Progress value={progress} aria-label={`Uploading ${chosen.folder.name}`} />
          <p className="text-xs text-muted-foreground">
            Uploading {chosen.folder.name}, {Math.round(progress * 100)}%
          </p>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        A skill is instructions that the lead follows, and it may come with scripts that code can run in a conversation. Upload
        only skills you trust. They are copied into the lab, so a later change to the folder is not picked up.
      </p>
      <DialogFooter>
        {working ? (
          <Button type="button" variant="outline" onClick={() => sending.current?.abort()}>
            <X />
            Cancel the upload
          </Button>
        ) : (
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
        )}
        <Button ref={send} type="button" disabled={chosen === null || wrong !== null || working || reading} onClick={() => void upload()}>
          <Upload />
          {working ? "Uploading…" : "Upload"}
        </Button>
      </DialogFooter>
    </>
  );
}

// Where a skill of a person's own is put in from a folder that they choose, or drop on the page, as it is on their machine
export function SkillUpload({
  open,
  onOpenChange,
  skills,
  onPutIn,
  onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  skills: SkillInfo[];
  onPutIn: (result: SkillsPutIn) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  // While a folder is being sent the dialog is not closed from under it, which would lose what the server answers
  const [busy, setBusy] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && busy) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-xl" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Upload skill</DialogTitle>
          <DialogDescription>Give the lab a skill of your own from a folder on this machine.</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          <UploadBody skills={skills} onPutIn={onPutIn} onBusy={setBusy} onClose={() => onOpenChange(false)} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
