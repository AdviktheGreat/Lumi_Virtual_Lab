"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { CodeTab } from "@/components/settings-code";
import { KeysTab } from "@/components/settings-keys";
import { ModelTab } from "@/components/settings-model";
import { ScientistsTab, useScientistEditor } from "@/components/settings-scientists";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { returnFocusTo } from "@/lib/focus";
import { changesOf, draftOf, type Draft } from "@/lib/settings";
import type { KeyStatuses, Settings } from "@/lib/types";
import { useSettingsData } from "@/lib/use-settings-data";

export type SettingsTab = "model" | "keys" | "code" | "scientists";

const TABS: { value: SettingsTab; label: string }[] = [
  { value: "model", label: "Model" },
  { value: "keys", label: "Keys" },
  { value: "code", label: "Code" },
  { value: "scientists", label: "Scientists" },
];

function isTab(value: string): value is SettingsTab {
  return TABS.some((tab) => tab.value === value);
}

// What the settings of a new conversation are, and what can be chosen for them. What is changed is kept when Save is
// pressed, and asked about if it would be lost on closing. Keys and scientists are kept as each is given.
export function SettingsDialog({
  settings,
  tab: first,
  opener,
  onClose,
}: {
  settings: Settings;
  tab: SettingsTab;
  // What had the focus when they were opened, which has it again once they are closed
  opener: HTMLElement | null;
  onClose: () => void;
}) {
  const { report, setSettings } = useServer();
  const data = useSettingsData();
  const editor = useScientistEditor();
  const [saved, setSaved] = useState(settings);
  const [draft, setDraft] = useState<Draft>(() => draftOf(settings));
  const [typingModel, setTypingModel] = useState(false);
  const [tab, setTab] = useState(first);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const { changes, problems } = changesOf(draft, saved);
  const changed = Object.keys(changes).length > 0;
  const invalid = Object.keys(problems).length > 0;
  const unsaved = changed || invalid || editor.unsaved;

  function edit(next: Partial<Draft>) {
    setDraft((was) => ({ ...was, ...next }));
    setProblem(null);
    setNotice(null);
  }

  async function save() {
    if (!changed || invalid || saving) return;
    setSaving(true);
    setProblem(null);
    setNotice(null);
    try {
      const kept = await api.changeSettings(changes);
      setSaved(kept);
      setDraft(draftOf(kept));
      setSettings(kept);
      setNotice("Saved. New conversations use these settings.");
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setSaving(false);
    }
  }

  // What closes it, however it is asked to: when something would be lost, it asks, and asking again takes the question back
  function requestClose() {
    if (!unsaved) onClose();
    else setConfirming((asking) => !asking);
  }

  function keysChanged(statuses: KeyStatuses) {
    data.setKeys(statuses);
    void data.refreshModels();
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) requestClose();
      }}
    >
      <DialogContent
        className="h-[min(40rem,calc(100dvh-2rem))] sm:max-w-2xl"
        onCloseAutoFocus={returnFocusTo(opener)}
      >
        <DialogHeader>
          <div className="flex items-center justify-between gap-2">
            <DialogTitle className="text-lg">Settings</DialogTitle>
            <Button variant="ghost" size="icon-sm" onClick={requestClose} aria-label="Close the settings">
              <X />
            </Button>
          </div>
          <DialogDescription>
            What the model, the spending, and the code are for conversations you start from now on. Ones already begun keep
            what they began with.
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (isTab(value)) setTab(value);
          }}
          className="min-h-0 flex-1"
        >
          <TabsList aria-label="Parts of the settings">
            {TABS.map(({ value, label }) => (
              <TabsTrigger key={value} value={value}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="model" className="overflow-y-auto pr-1">
            <fieldset disabled={saving} className="min-w-0">
              <ModelTab
                draft={draft}
                onChange={edit}
                typing={typingModel}
                onTyping={setTypingModel}
                problems={problems}
                models={data.models}
                keys={data.keys}
                onAddKey={() => setTab("keys")}
              />
            </fieldset>
          </TabsContent>
          <TabsContent value="keys" className="overflow-y-auto pr-1">
            <KeysTab keys={data.keys} onChanged={keysChanged} />
          </TabsContent>
          <TabsContent value="code" className="overflow-y-auto pr-1">
            <fieldset disabled={saving} className="min-w-0">
              <CodeTab draft={draft} onChange={edit} keys={data.keys} />
            </fieldset>
          </TabsContent>
          <TabsContent value="scientists" className="overflow-y-auto pr-1">
            <ScientistsTab library={data.scientists} editor={editor} onChanged={data.setScientists} />
          </TabsContent>
        </Tabs>

        {confirming ? (
          <DialogFooter className="border-t border-border pt-3">
            <p role="alert" className="text-sm sm:mr-auto">
              What you changed is not saved.
            </p>
            <Button variant="outline" onClick={() => setConfirming(false)} autoFocus>
              Keep editing
            </Button>
            <Button variant="destructive" onClick={onClose}>
              Discard the changes
            </Button>
          </DialogFooter>
        ) : (
          <DialogFooter className="border-t border-border pt-3">
            {problem && (
              <p role="alert" className="text-sm text-destructive sm:mr-auto">
                {problem}
              </p>
            )}
            {notice && (
              <p role="status" className="text-sm text-muted-foreground sm:mr-auto">
                {notice}
              </p>
            )}
            <Button variant="outline" onClick={requestClose}>
              Close
            </Button>
            {(changed || invalid) && (
              <Button onClick={() => void save()} disabled={!changed || invalid || saving}>
                Save changes
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
