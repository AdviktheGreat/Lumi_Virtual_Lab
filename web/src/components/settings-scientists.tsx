"use client";

import { useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { describedBy, Field, Section } from "@/components/settings-fields";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import {
  checkScientist,
  draftOfScientist,
  EMPTY_SCIENTIST,
  isChanged,
  MAX_PART,
  MAX_TITLE,
  PARTS,
  type Part,
  type ScientistDraft,
} from "@/lib/scientists";
import type { LibraryScientist } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

export type Editing = { mode: "new" } | { mode: "edit"; original: LibraryScientist };

export interface ScientistEditor {
  editing: Editing | null;
  draft: ScientistDraft;
  // Whether the problems with what was written are shown, which they are once it has been tried to save
  tried: boolean;
  // Whether there is something written that is not kept
  unsaved: boolean;
  begin: (editing: Editing) => void;
  change: (part: Part, value: string) => void;
  tryToSave: () => void;
  cancel: () => void;
}

// A scientist being written or edited, which is held where the settings are, so that it is not lost on moving to another
// part of them, and is told of when they are closed
export function useScientistEditor(): ScientistEditor {
  const [editing, setEditing] = useState<Editing | null>(null);
  const [draft, setDraft] = useState<ScientistDraft>(EMPTY_SCIENTIST);
  const [tried, setTried] = useState(false);

  const unsaved =
    editing === null
      ? false
      : editing.mode === "new"
        ? PARTS.some(({ key }) => draft[key].trim() !== "")
        : isChanged(draft, editing.original);

  return {
    editing,
    draft,
    tried,
    unsaved,
    begin: (next) => {
      setEditing(next);
      setDraft(next.mode === "edit" ? draftOfScientist(next.original) : EMPTY_SCIENTIST);
      setTried(false);
    },
    change: (part, value) => setDraft((was) => ({ ...was, [part]: value })),
    tryToSave: () => setTried(true),
    cancel: () => {
      setEditing(null);
      setDraft(EMPTY_SCIENTIST);
      setTried(false);
    },
  };
}

function ScientistForm({
  editor,
  library,
  onSaved,
}: {
  editor: ScientistEditor;
  library: LibraryScientist[];
  onSaved: (library: LibraryScientist[], title: string) => void;
}) {
  const { report } = useServer();
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const editing = editor.editing;
  const checked = checkScientist(editor.draft, library, editing?.mode === "new");
  const shown = editor.tried ? checked.problems : {};
  const titleHint =
    editing?.mode !== "edit"
      ? PARTS[0].hint
      : editing.original.builtin
        ? "A scientist is known by their title, which stays as it is. Saving keeps your own version, which is used in place of the built-in one."
        : "A scientist is known by their title, which stays as it is.";

  async function save() {
    editor.tryToSave();
    if (checked.scientist === null) return;
    setSaving(true);
    setProblem(null);
    try {
      const kept = await api.saveScientist(checked.scientist);
      onSaved(kept, checked.scientist.title);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
      setSaving(false);
    }
  }

  return (
    <form
      aria-label={editing?.mode === "edit" ? `Edit ${editing.original.title}` : "A new scientist"}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4"
    >
      {PARTS.map(({ key, label, hint }) => {
        const id = `settings-scientist-${key}`;
        const described = describedBy(id, { hint: true, problem: shown[key] !== undefined });

        return (
          <Field key={key} id={id} label={label} hint={key === "title" ? titleHint : hint} problem={shown[key]}>
            {key === "title" ? (
              <Input
                id={id}
                value={editor.draft.title}
                onChange={(event) => editor.change("title", event.target.value)}
                maxLength={MAX_TITLE}
                readOnly={saving || editing?.mode === "edit"}
                aria-invalid={shown.title !== undefined}
                aria-describedby={described}
                autoComplete="off"
              />
            ) : (
              <Textarea
                id={id}
                value={editor.draft[key]}
                onChange={(event) => editor.change(key, event.target.value)}
                maxLength={MAX_PART}
                rows={3}
                readOnly={saving}
                aria-invalid={shown[key] !== undefined}
                aria-describedby={described}
              />
            )}
          </Field>
        );
      })}
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={editor.cancel} disabled={saving}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          Save scientist
        </Button>
      </div>
    </form>
  );
}

function ScientistRow({
  scientist,
  onEdit,
  onRemove,
}: {
  scientist: LibraryScientist;
  onEdit: () => void;
  onRemove: (button: HTMLButtonElement) => void;
}) {
  return (
    <li className="flex items-start gap-2 rounded-lg border border-border p-3" data-testid="scientist">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">{scientist.title}</span>
          <Badge variant={scientist.builtin ? "outline" : "secondary"}>{scientist.builtin ? "Built in" : "Yours"}</Badge>
        </div>
        <p className="line-clamp-2 text-xs text-muted-foreground">{scientist.expertise}</p>
      </div>
      <Button variant="ghost" size="icon-sm" onClick={onEdit} aria-label={`Edit ${scientist.title}`}>
        <Pencil />
      </Button>
      {!scientist.builtin && (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={(event) => onRemove(event.currentTarget)}
          aria-label={`Delete ${scientist.title}`}
        >
          <Trash2 />
        </Button>
      )}
    </li>
  );
}

export function ScientistsTab({
  library,
  editor,
  onChanged,
}: {
  library: Loaded<LibraryScientist[]>;
  editor: ScientistEditor;
  onChanged: (library: LibraryScientist[]) => void;
}) {
  const { report } = useServer();
  // The one asked about stays set after the question is closed, so that it is not blanked while it fades
  const [removing, setRemoving] = useState<LibraryScientist | null>(null);
  const [asking, setAsking] = useState(false);
  // What had the focus when the question was asked, which has it again when the question is closed
  const asker = useRef<HTMLButtonElement | null>(null);
  const adder = useRef<HTMLButtonElement | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function remove(scientist: LibraryScientist) {
    setProblem(null);
    setDone(null);
    try {
      onChanged(await api.removeScientist(scientist.title));
      setDone(`Deleted ${scientist.title}.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  if (library.kind === "loading") return <p className="text-sm text-muted-foreground">Loading the scientists…</p>;
  if (library.kind === "failed") {
    return (
      <p role="alert" className="text-sm text-destructive">
        {describeError(library.error)}
      </p>
    );
  }

  if (editor.editing !== null) {
    return (
      <Section title={editor.editing.mode === "edit" ? "Edit a scientist" : "A new scientist"}>
        <ScientistForm
          editor={editor}
          library={library.value}
          onSaved={(kept, title) => {
            onChanged(kept);
            editor.cancel();
            setDone(`Saved ${title}.`);
          }}
        />
      </Section>
    );
  }

  return (
    <Section>
      <p className="text-sm text-muted-foreground">
        The lead scientist can bring any of these into a conversation. Change one, or add your own: yours are kept with
        the workspace.
      </p>
      <div>
        <Button
          ref={adder}
          variant="outline"
          onClick={() => {
            setDone(null);
            setProblem(null);
            editor.begin({ mode: "new" });
          }}
        >
          <Plus />
          Add a scientist
        </Button>
      </div>
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
      <ul aria-label="Scientists" className="flex flex-col gap-2">
        {library.value.map((scientist) => (
          <ScientistRow
            key={scientist.title}
            scientist={scientist}
            onEdit={() => {
              setDone(null);
              setProblem(null);
              editor.begin({ mode: "edit", original: scientist });
            }}
            onRemove={(button) => {
              asker.current = button;
              setRemoving(scientist);
              setAsking(true);
            }}
          />
        ))}
      </ul>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            // Nothing opened the question but a button of the list, which is gone when its scientist was deleted
            event.preventDefault();
            const back = asker.current?.isConnected ? asker.current : adder.current;
            back?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {removing?.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away your version. If the lab has a built-in scientist with this title, theirs is used again.
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
    </Section>
  );
}
