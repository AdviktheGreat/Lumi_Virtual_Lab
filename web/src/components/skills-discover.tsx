"use client";

import { useMemo, useRef, useState } from "react";
import { Download, Search } from "lucide-react";
import { LibraryRow } from "@/components/library-row";
import { PutInResult } from "@/components/skill-put-in-result";
import { SkillsMeter } from "@/components/skills-meter";
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
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { catalogAdded, licenseWarnings, matchingLibrary, SKILLS_SHOWN, tokensSaid } from "@/lib/skills";
import type { LibraryCategory, SkillLibrary, Skills, SkillsPutIn } from "@/lib/types";

// A button that cannot be used right now but keeps the focus it has, which a disabled one would not
const UNAVAILABLE = "aria-disabled:pointer-events-none aria-disabled:opacity-50";

// The categories under the group each is in, in the order the library lists them
function groupsOf(categories: LibraryCategory[]): { group: string; categories: LibraryCategory[] }[] {
  const groups: { group: string; categories: LibraryCategory[] }[] = [];
  for (const category of categories) {
    const found = groups.find((each) => each.group === category.group);
    if (found) found.categories.push(category);
    else groups.push({ group: category.group, categories: [category] });
  }

  return groups;
}

function Source({ library }: { library: SkillLibrary }) {
  const { source } = library;
  const total = library.skills.length;
  const inYours = library.skills.filter((skill) => skill.installed).length;

  return (
    <p className="text-sm text-muted-foreground" data-testid="library-source">
      {total} skill{total === 1 ? "" : "s"}
      {source.author && <> by {source.author}</>}
      {source.name && source.url && (
        <>
          {" "}
          in{" "}
          <a href={source.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
            {source.name}
          </a>
        </>
      )}
      {source.version && <>, version {source.version}</>}
      {source.license && <>, under the {source.license} License and, where a skill says so, its own</>}. {inYours} in your skills.
    </p>
  );
}

// The skills that come with the lab to be put in: found by what they are for or by category, chosen, read before they are
// put in, and copied into the lab's own skills, where they are on like any other and cost every conversation a line of the
// list the lead is given
export function SkillsDiscover({
  library,
  skills,
  onPutIn,
  onShowYours,
}: {
  library: SkillLibrary;
  skills: Skills;
  onPutIn: (result: SkillsPutIn) => void;
  onShowYours: () => void;
}) {
  const { report } = useServer();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [shown, setShown] = useState(SKILLS_SHOWN);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [asking, setAsking] = useState(false);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<SkillsPutIn | null>(null);
  const submit = useRef<HTMLButtonElement | null>(null);
  const groups = useMemo(() => groupsOf(library.categories), [library.categories]);

  const found = matchingLibrary(library.skills, query, category);
  const listed = found.slice(0, shown);
  const filtering = query.trim() !== "" || category !== "";
  const open = found.filter((skill) => !skill.installed);
  // What was chosen is kept while the search changes, and a skill that has been put in is not one to be put in again
  const chosen = library.skills.filter((skill) => picked.has(skill.name) && !skill.installed);
  const allChosen = open.every((skill) => picked.has(skill.name));
  const warnings = licenseWarnings(chosen);

  function choose(names: string[], on: boolean) {
    setPicked((was) => {
      const next = new Set(was);
      for (const name of names) {
        if (on) next.add(name);
        else next.delete(name);
      }

      return next;
    });
  }

  async function putIn() {
    const names = chosen.map((skill) => skill.name);
    setWorking(true);
    setProblem(null);
    setResult(null);
    try {
      const done = await api.putInLibrarySkills(names);
      setResult(done);
      setPicked(new Set());
      onPutIn(done);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setWorking(false);
    }
  }

  if (library.skills.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <p role="status" className="text-sm text-muted-foreground">
          The lab has no library of skills to put in.
        </p>
        {library.problems.length > 0 && (
          <ul aria-label="Problems with the library" className="list-disc pl-4 text-xs text-muted-foreground">
            {library.problems.map((each) => (
              <li key={each} className="break-words">
                {each}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Source library={library} />
      <SkillsMeter catalog={skills.catalog} />
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setShown(SKILLS_SHOWN);
            }}
            placeholder="Search the library"
            aria-label="Search the library"
            autoComplete="off"
            className="pl-8"
          />
        </div>
        <div className="sm:w-72">
          <NativeSelect
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setShown(SKILLS_SHOWN);
            }}
            aria-label="Category"
          >
            <option value="">All categories</option>
            {groups.map(({ group, categories }) => (
              <optgroup key={group} label={group}>
                {categories.map((each) => (
                  <option key={each.name} value={each.name}>
                    {each.name} ({each.count})
                  </option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <p role="status" className="text-sm text-muted-foreground" data-testid="library-count">
          {filtering ? `${found.length} of ${library.skills.length} skills` : `${library.skills.length} skills`}
          {chosen.length > 0 && `, ${chosen.length} chosen`}
        </p>
        <Button
          variant="outline"
          size="sm"
          className={`ml-auto ${UNAVAILABLE}`}
          aria-disabled={open.length === 0 || allChosen}
          onClick={() => {
            if (open.length > 0 && !allChosen) choose(open.map((skill) => skill.name), true);
          }}
        >
          {filtering ? "Choose these" : "Choose all"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className={UNAVAILABLE}
          aria-disabled={chosen.length === 0}
          onClick={() => {
            if (chosen.length > 0) setPicked(new Set());
          }}
        >
          Clear
        </Button>
        <Button
          ref={submit}
          size="sm"
          className={UNAVAILABLE}
          aria-disabled={chosen.length === 0 || working}
          onClick={() => {
            if (chosen.length > 0 && !working) setAsking(true);
          }}
        >
          <Download />
          {working ? "Putting them in…" : chosen.length > 0 ? `Put in ${chosen.length}` : "Put in"}
        </Button>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      {result !== null && (
        <div className="flex flex-col items-start gap-2">
          <PutInResult result={result} />
          {result.installed.length > 0 && (
            <Button variant="outline" size="sm" onClick={onShowYours}>
              See them in your skills
            </Button>
          )}
        </div>
      )}
      {found.length === 0 ? (
        <p role="status" className="text-sm text-muted-foreground">
          No skill has all of those words{category !== "" ? " in that category" : ""}.
        </p>
      ) : (
        <ul aria-label="Skills of the library" className="flex flex-col gap-2">
          {listed.map((skill) => (
            <LibraryRow
              key={skill.name}
              skill={skill}
              chosen={picked.has(skill.name)}
              onChoose={(on) => choose([skill.name], on)}
            />
          ))}
        </ul>
      )}
      {found.length > listed.length && (
        <Button variant="outline" size="sm" className="self-start" onClick={() => setShown((was) => was + SKILLS_SHOWN)}>
          Show more ({found.length - listed.length} left)
        </Button>
      )}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            submit.current?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>
              Put in {chosen.length} skill{chosen.length === 1 ? "" : "s"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              A skill is instructions that the lead follows, and it may come with scripts that code can run in a
              conversation. These are copied from the library that comes with the lab into your skills, where they are on
              like any other. Together they add {tokensSaid(catalogAdded(chosen))} to the start of every conversation, and
              you can turn them off, or delete them, in your skills.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {warnings.length > 0 && (
            <ul aria-label="About their licenses" className="flex flex-col gap-1 text-sm">
              {warnings.map((warning) => (
                <li key={warning} className="break-words">
                  {warning}
                </li>
              ))}
            </ul>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void putIn()}>Put them in</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
