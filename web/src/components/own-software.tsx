"use client";

import { useId, useRef, useState } from "react";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { checkSoftware, MAX_DESCRIPTION, MAX_SOFTWARE_NAME } from "@/lib/own";
import type { Own, OwnSoftware } from "@/lib/types";

// Says what the change was, and what the lab was given as it now is
type Changed = (own: Own, said: string) => void;

function SoftwareForm({
  given,
  changing,
  onSaved,
  onCancel,
  submit,
}: {
  given: readonly OwnSoftware[];
  // The software being changed, whose name stays as it is, or null for some that is new
  changing: OwnSoftware | null;
  onSaved: Changed;
  onCancel: () => void;
  submit: React.Ref<HTMLButtonElement>;
}) {
  const { report } = useServer();
  const id = useId();
  const [name, setName] = useState(changing?.name ?? "");
  const [description, setDescription] = useState(changing?.description ?? "");
  const [tried, setTried] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const checked = checkSoftware(name, description, given, changing === null);
  const shown = tried ? checked.problems : {};
  const nameId = `${id}-name`;
  const descriptionId = `${id}-description`;

  async function save() {
    setTried(true);
    if (checked.software === null) return;
    setSaving(true);
    setProblem(null);
    try {
      const { name: title, description: described } = checked.software;
      const own = await api.saveOwnSoftware(title, described);
      onSaved(own, `Saved ${title}.`);
      if (changing === null) {
        setName("");
        setDescription("");
        setTried(false);
      }
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      aria-label={changing === null ? "Give the lab some software" : `Change ${changing.name}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={nameId}
        label="Name"
        hint={changing === null ? "What it is called, such as samtools or Cell Ranger." : "It is known by its name, which stays as it is."}
        problem={shown.name}
      >
        <Input
          id={nameId}
          value={name}
          onChange={(event) => setName(event.target.value)}
          readOnly={saving || changing !== null}
          maxLength={MAX_SOFTWARE_NAME * 4}
          autoComplete="off"
          aria-invalid={shown.name !== undefined}
          aria-describedby={describedBy(nameId, { hint: true, problem: shown.name !== undefined })}
        />
      </Field>
      <Field
        id={descriptionId}
        label="What it is for"
        hint="What you use it for and anything the lead should know of it, such as its version."
        problem={shown.description}
      >
        <Textarea
          id={descriptionId}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={3}
          readOnly={saving}
          maxLength={MAX_DESCRIPTION * 4}
          autoFocus={changing !== null}
          aria-invalid={shown.description !== undefined}
          aria-describedby={describedBy(descriptionId, { hint: true, problem: shown.description !== undefined })}
        />
      </Field>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <div className="flex gap-2">
        <Button ref={submit} type="submit" disabled={saving}>
          {changing === null && <Plus />}
          {changing === null ? "Add the software" : "Save"}
        </Button>
        {changing !== null && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

// The software the person has, which is told to the lead and is not installed by the lab
export function OwnSoftwareSection({ own, onChanged }: { own: Own; onChanged: Changed }) {
  const { report } = useServer();
  const [changing, setChanging] = useState<OwnSoftware | null>(null);
  // The one asked about stays set after the question is closed, so that it is not blanked while it fades
  const [removing, setRemoving] = useState<OwnSoftware | null>(null);
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

  async function remove(software: OwnSoftware) {
    setProblem(null);
    setDone(null);
    try {
      changed(await api.removeOwnSoftware(software.name), `Deleted ${software.name}.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {own.software.length === 0 ? (
        <p className="text-sm text-muted-foreground">You have not told the lab of any software yet.</p>
      ) : (
        <ul aria-label="Your software" className="flex flex-col gap-2">
          {own.software.map((software) =>
            changing?.name === software.name ? (
              <li key={software.name} data-testid="own-software">
                <SoftwareForm
                  given={own.software}
                  changing={software}
                  onSaved={(next, said) => {
                    setChanging(null);
                    changed(next, said);
                  }}
                  onCancel={() => setChanging(null)}
                  submit={null}
                />
              </li>
            ) : (
              <li
                key={software.name}
                className="flex items-start gap-2 rounded-lg border border-border p-3"
                data-testid="own-software"
              >
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="break-words text-sm font-medium">{software.name}</span>
                  <p className="break-words text-sm">{software.description}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => {
                    setDone(null);
                    setChanging(software);
                  }}
                  aria-label={`Change ${software.name}`}
                >
                  <Pencil />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={(event) => {
                    asker.current = event.currentTarget;
                    setRemoving(software);
                    setAsking(true);
                  }}
                  aria-label={`Delete ${software.name}`}
                >
                  <Trash2 />
                </Button>
              </li>
            ),
          )}
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
      <Section title="Add software">
        <SoftwareForm given={own.software} changing={null} onSaved={changed} onCancel={() => undefined} submit={adder} />
      </Section>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            // Nothing opened the question but a button of the list, which is gone when its software was deleted
            event.preventDefault();
            const back = asker.current?.isConnected ? asker.current : adder.current;
            back?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {removing?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              The lead is no longer told that you have it. It is not uninstalled from anywhere.
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
