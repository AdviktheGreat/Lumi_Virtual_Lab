"use client";

import { useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { describeError } from "@/lib/errors";
import {
  choiceKept,
  choiceStart,
  givenSkills,
  howManyChosen,
  matching,
  pickedWhen,
  SKILLS_SHOWN,
} from "@/lib/skills";
import type { Skills } from "@/lib/types";
import { useSkills } from "@/lib/use-skills";

// A button that cannot be used right now but keeps the focus it has, which a disabled one would not
const UNAVAILABLE = "aria-disabled:pointer-events-none aria-disabled:opacity-50";

type Props =
  | {
      // The skills a conversation is to begin with are chosen: from those that were chosen before, or where none have been,
      // those that are on for new conversations. What is chosen is given to onDone, which is null where it is those.
      kind: "choose";
      chosen: string[] | null;
      onDone: (chosen: string[] | null) => void;
      onClose: () => void;
    }
  | {
      // The skills a conversation that has begun was given are shown, which is not for changing
      kind: "view";
      had: string[];
      onClose: () => void;
    };

function Searching({
  query,
  onChange,
  label,
}: {
  query: string;
  onChange: (query: string) => void;
  label: string;
}) {
  return (
    <div className="relative">
      <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        value={query}
        onChange={(event) => onChange(event.target.value)}
        placeholder={label}
        aria-label={label}
        autoComplete="off"
        className="pl-8"
      />
    </div>
  );
}

function NoSkills() {
  return (
    <p role="status" className="text-sm text-muted-foreground">
      There are no skills yet. They are put in, and turned on and off for every new program, on the{" "}
      <Link href="/skills" className="underline underline-offset-2">
        Skills page
      </Link>
      .
    </p>
  );
}

function Choosing({
  library,
  chosen,
  onDone,
  onClose,
}: {
  library: Skills;
  chosen: string[] | null;
  onDone: (chosen: string[] | null) => void;
  onClose: () => void;
}) {
  const skills = library.skills;
  // What was changed here, which is nothing until it is
  const [changed, setChanged] = useState<Set<string> | null>(null);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(SKILLS_SHOWN);
  const picked = changed ?? choiceStart(skills, chosen);
  const found = matching(skills, query);
  const listed = found.slice(0, shown);
  const searching = query.trim() !== "";
  const allIn = found.every((skill) => picked.has(skill.name));
  const noneIn = found.every((skill) => !picked.has(skill.name));

  function pick(names: string[], on: boolean) {
    setChanged(pickedWhen(picked, names, on));
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Choose the skills</DialogTitle>
        <DialogDescription>
          The lead is told what each skill is for in every message, which costs a little, and reads a skill when the work calls
          for it. A program keeps the skills it begins with.
        </DialogDescription>
      </DialogHeader>
      {skills.length === 0 ? (
        <NoSkills />
      ) : (
        <div className="flex min-h-0 flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <p role="status" className="text-sm text-muted-foreground" data-testid="skills-chosen">
              {howManyChosen(picked.size, skills.length)}
            </p>
            <Button
              variant="outline"
              size="sm"
              className={`ml-auto ${UNAVAILABLE}`}
              aria-disabled={allIn}
              onClick={() => {
                if (!allIn) pick(found.map((skill) => skill.name), true);
              }}
            >
              {searching ? "Choose these" : "Choose all"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={UNAVAILABLE}
              aria-disabled={noneIn}
              onClick={() => {
                if (!noneIn) pick(found.map((skill) => skill.name), false);
              }}
            >
              {searching ? "Leave these out" : "Leave all out"}
            </Button>
          </div>
          <Searching
            query={query}
            onChange={(next) => {
              setQuery(next);
              setShown(SKILLS_SHOWN);
            }}
            label="Search the skills"
          />
          {found.length === 0 ? (
            <p role="status" className="text-sm text-muted-foreground">
              No skill has all of those words.
            </p>
          ) : (
            <ul aria-label="Skills" className="-mx-1 flex max-h-72 flex-col gap-1 overflow-y-auto px-1">
              {listed.map((skill) => (
                <li key={skill.name} data-testid="skill-choice">
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-accent has-[:focus-visible]:bg-accent">
                    <Checkbox
                      checked={picked.has(skill.name)}
                      onChange={(event) => pick([skill.name], event.target.checked)}
                      aria-label={skill.name}
                      className="mt-1"
                    />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <code className="break-all text-sm font-medium">{skill.name}</code>
                      <span className="line-clamp-2 break-words text-xs text-muted-foreground">{skill.description}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {found.length > listed.length && (
            <Button variant="outline" size="sm" className="self-start" onClick={() => setShown((was) => was + SKILLS_SHOWN)}>
              Show more ({found.length - listed.length} left)
            </Button>
          )}
        </div>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={() => onDone(choiceKept(skills, picked))} disabled={skills.length === 0}>
          Use these
        </Button>
      </DialogFooter>
    </>
  );
}

function Viewing({ library, had, onClose }: { library: Skills; had: string[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(SKILLS_SHOWN);
  const given = givenSkills(library.skills, had).map(({ name, description }) => ({
    name,
    description: description ?? "",
    missing: description === null,
  }));
  const found = matching(given, query);
  const listed = found.slice(0, shown);

  return (
    <>
      <DialogHeader>
        <DialogTitle>The skills of this program</DialogTitle>
        <DialogDescription>
          A program keeps the skills it was begun with, and goes on with those that are still there. Begin another to
          choose different ones.
        </DialogDescription>
      </DialogHeader>
      {had.length === 0 ? (
        <p role="status" className="text-sm text-muted-foreground">
          This program was given no skills.
        </p>
      ) : (
        <div className="flex min-h-0 flex-col gap-3">
          <p role="status" className="text-sm text-muted-foreground" data-testid="skills-given">
            {had.length} skill{had.length === 1 ? "" : "s"}
          </p>
          {had.length > 8 && (
            <Searching
              query={query}
              onChange={(next) => {
                setQuery(next);
                setShown(SKILLS_SHOWN);
              }}
              label="Search its skills"
            />
          )}
          {found.length === 0 ? (
            <p role="status" className="text-sm text-muted-foreground">
              No skill has all of those words.
            </p>
          ) : (
            <ul aria-label="Skills of this program" className="-mx-1 flex max-h-72 flex-col gap-1.5 overflow-y-auto px-1">
              {listed.map((skill) => (
                <li key={skill.name} data-testid="skill-given" className="flex flex-col rounded-md px-2 py-1">
                  <code className="break-all text-sm font-medium">{skill.name}</code>
                  <span className="line-clamp-2 break-words text-xs text-muted-foreground">
                    {skill.missing ? "It is not there any more, so the lead goes on without it." : skill.description}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {found.length > listed.length && (
            <Button variant="outline" size="sm" className="self-start" onClick={() => setShown((was) => was + SKILLS_SHOWN)}>
              Show more ({found.length - listed.length} left)
            </Button>
          )}
        </div>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      </DialogFooter>
    </>
  );
}

// Where the skills a conversation is given are chosen as it begins, or looked at once it has: a list of those there are, which
// is read from the server when this opens, since a folder of them may have been changed since the page did
export function SkillsDialog(props: Props) {
  const { report } = useServer();
  const { skills, reload } = useSkills(report);
  const library = skills.kind === "ready" ? skills.value : null;

  return (
    <Dialog open onOpenChange={(open) => !open && props.onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="skills-dialog" aria-busy={skills.kind === "loading"}>
        {library !== null ? (
          props.kind === "choose" ? (
            <Choosing library={library} chosen={props.chosen} onDone={props.onDone} onClose={props.onClose} />
          ) : (
            <Viewing library={library} had={props.had} onClose={props.onClose} />
          )
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{props.kind === "choose" ? "Choose the skills" : "The skills of this program"}</DialogTitle>
              <DialogDescription>
                {skills.kind === "loading" ? "Reading the skills…" : "The skills could not be read."}
              </DialogDescription>
            </DialogHeader>
            {skills.kind === "failed" && (
              <div className="flex flex-col items-start gap-2">
                <p role="alert" className="text-sm text-destructive">
                  {describeError(skills.error)}
                </p>
                <Button variant="outline" size="sm" onClick={reload}>
                  Try again
                </Button>
              </div>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={props.onClose}>
                {props.kind === "choose" ? "Cancel" : "Close"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
