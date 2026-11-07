"use client";

import { useState } from "react";
import Link from "next/link";
import { FolderInput, Loader2, Plus } from "lucide-react";
import { CampaignDialog } from "@/components/campaign-dialog";
import { useChats } from "@/components/chats-provider";
import { Notice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Radio } from "@/components/ui/radio";
import { api } from "@/lib/api";
import { campaignAddress } from "@/lib/campaigns";
import { problemOf, type Problem } from "@/lib/errors";
import { UNTITLED } from "@/lib/history";
import { cn } from "@/lib/utils";

// What shows in the header of a program which campaign it is one of, and opens the choice of it
export function CampaignButton({ name, onClick }: { name: string | null; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      onClick={onClick}
      title={name === null ? "Make this program part of a campaign" : `Part of the campaign ${name}. Change it.`}
      data-testid="program-campaign-button"
      className="max-w-44 shrink-0 gap-1.5 rounded-4xl"
    >
      <FolderInput className="size-3 shrink-0" aria-hidden />
      <span className="truncate">{name ?? "Add to a campaign"}</span>
    </Button>
  );
}

// Which campaign a program is one of, to be changed: one of those there are, or none. A new campaign can be made here, and
// is chosen, and nothing is moved until the choice is saved.
export function MoveDialog({
  chat,
  onClose,
  onClosed,
}: {
  chat: { id: string; title: string; campaign: string | null };
  onClose: () => void;
  // What the focus goes to when it is closed, if not where it was
  onClosed?: (event: Event) => void;
}) {
  const { campaigns, refresh } = useChats();
  const { report } = useServer();
  // "" is none, as it is for the radio buttons that choose it
  const [chosen, setChosen] = useState(chat.campaign ?? "");
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const current = campaigns?.find((campaign) => campaign.id === chat.campaign) ?? null;
  const unchanged = chosen === (current?.id ?? "");

  async function save() {
    if (saving || unchanged) return;
    setSaving(true);
    setProblem(null);
    try {
      await api.setCampaign(chat.id, chosen === "" ? null : chosen);
      await refresh();
      onClose();
    } catch (error) {
      report(error);
      setProblem(problemOf(error));
      setSaving(false);
    }
  }

  const options = [{ id: "", name: "No campaign" }, ...(campaigns ?? [])];

  return (
    <>
      <Dialog open onOpenChange={(open) => !open && !saving && onClose()}>
        <DialogContent className="sm:max-w-md" data-testid="move-dialog" onCloseAutoFocus={onClosed}>
          <DialogHeader>
            <DialogTitle>Campaign of this program</DialogTitle>
            <DialogDescription>
              “{chat.title || UNTITLED}” can be part of one campaign. The lead is told the goal of its campaign from the next message it
              answers.
            </DialogDescription>
          </DialogHeader>

          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <fieldset className="flex max-h-72 flex-col gap-1 overflow-y-auto" disabled={saving}>
              <legend className="sr-only">Campaign</legend>
              {options.map((option) => (
                <label
                  key={option.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors hover:bg-accent has-[:disabled]:cursor-not-allowed has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                    option.id === chosen && "bg-highlight text-highlight-foreground hover:bg-highlight",
                  )}
                >
                  <Radio
                    name="campaign-choice"
                    value={option.id}
                    checked={option.id === chosen}
                    onChange={() => {
                      setChosen(option.id);
                      setProblem(null);
                    }}
                    className="focus-visible:ring-0"
                  />
                  <span className={cn("min-w-0 flex-1 truncate", option.id === "" && "text-muted-foreground")}>{option.name}</span>
                </label>
              ))}
            </fieldset>

            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="outline" size="sm" disabled={saving} onClick={() => setCreating(true)} data-testid="move-new-campaign">
                <Plus aria-hidden />
                New campaign
              </Button>
              {current !== null && (
                <Button asChild variant="link" size="sm">
                  <Link href={campaignAddress(current.id)} onClick={onClose}>
                    Open {current.name}
                  </Link>
                </Button>
              )}
            </div>

            {problem && <Notice tone="error">{problem.text}</Notice>}

            <DialogFooter>
              <Button type="button" variant="outline" disabled={saving} onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving || unchanged} data-testid="move-save">
                {saving && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
                Move
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {creating && (
        <CampaignDialog
          campaign={null}
          onSave={async (kept) => {
            const made = await api.makeCampaign(kept);
            await refresh();
            setChosen(made.id);
          }}
          onClose={() => setCreating(false)}
        />
      )}
    </>
  );
}
