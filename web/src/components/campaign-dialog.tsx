"use client";

import { useId, useState } from "react";
import { Loader2 } from "lucide-react";
import { Notice } from "@/components/messages";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { BRIEF_LIMIT, checkCampaign, draftOf, type CampaignDraft, type CampaignProblems } from "@/lib/campaigns";
import { problemOf, type Problem } from "@/lib/errors";
import { capTitle } from "@/lib/history";
import { lengthOf } from "@/lib/programs";
import type { Campaign, NewCampaign } from "@/lib/types";

// A campaign being made, or the name and goal of one being changed. Saving gives onSave what was typed, tidied, which may
// refuse it by throwing, and whose refusal is shown here, and which closes the dialog when it is done.
export function CampaignDialog({
  campaign,
  onSave,
  onClose,
}: {
  // The campaign that is being changed, or null for a new one
  campaign: Campaign | null;
  onSave: (kept: NewCampaign) => Promise<void>;
  onClose: () => void;
}) {
  const id = useId();
  const nameId = `${id}-name`;
  const briefId = `${id}-brief`;
  const [draft, setDraft] = useState<CampaignDraft>(() => draftOf(campaign));
  // What is wrong with what was typed, which is shown once it has been tried to keep it, and until it is typed over
  const [shown, setShown] = useState<CampaignProblems>({});
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const length = lengthOf(draft.brief.trim());

  function edit(next: Partial<CampaignDraft>) {
    setDraft((was) => ({ ...was, ...next }));
    setShown({});
    setProblem(null);
  }

  async function save() {
    if (saving) return;
    const { campaign: kept, problems } = checkCampaign(draft);
    setShown(problems);
    if (kept === null) {
      document.getElementById(problems.name !== undefined ? nameId : briefId)?.focus();

      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      await onSave(kept);
      onClose();
    } catch (error) {
      setProblem(problemOf(error));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !saving && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="campaign-dialog">
        <DialogHeader>
          <DialogTitle>{campaign === null ? "New campaign" : "Edit the campaign"}</DialogTitle>
          <DialogDescription>
            A campaign groups the programs that work toward one goal. The lead of each program is told the goal in every message it
            answers.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Field id={nameId} label="Name" problem={shown.name}>
            <Input
              id={nameId}
              value={draft.name}
              onChange={(event) => edit({ name: capTitle(event.target.value) })}
              placeholder="Nanobody screen against KP.3"
              autoComplete="off"
              autoFocus
              aria-invalid={shown.name !== undefined}
              aria-describedby={describedBy(nameId, { problem: shown.name !== undefined })}
            />
          </Field>
          <Field
            id={briefId}
            label="Goal"
            hint={`What the programs work toward, and what the lead should know of it. It can be left empty. ${length.toLocaleString("en-US")} of ${BRIEF_LIMIT.toLocaleString("en-US")} characters.`}
            problem={shown.brief}
          >
            <Textarea
              id={briefId}
              value={draft.brief}
              onChange={(event) => edit({ brief: event.target.value })}
              rows={6}
              placeholder="Find a nanobody that binds the spike of KP.3 and stays stable at 37 °C. Compare candidates by affinity, then by developability."
              className="max-h-64 overflow-y-auto"
              aria-invalid={shown.brief !== undefined}
              aria-describedby={describedBy(briefId, { hint: true, problem: shown.brief !== undefined })}
            />
          </Field>

          {problem && <Notice tone="error">{problem.text}</Notice>}

          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving} data-testid="campaign-save">
              {saving && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
              {campaign === null ? "Create" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
