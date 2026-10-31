"use client";

import { useEffect, useRef, useState } from "react";
import { useServer } from "@/components/server-provider";
import { api } from "./api";
import { problemOf, type Problem } from "./errors";
import { saveFile, type ExportFormat } from "./export";

export interface Exporter {
  // The format being made, if one is
  saving: ExportFormat | null;
  save: (format: ExportFormat) => Promise<void>;
}

// Saving a conversation as a document. The document is made by the server, which can fail to make a PDF, so what it says is
// given to onProblem, to be shown where the page shows what went wrong.
export function useExport(id: string, onProblem: (problem: Problem | null) => void): Exporter {
  const { report } = useServer();
  const [saving, setSaving] = useState<ExportFormat | null>(null);
  const running = useRef<AbortController | null>(null);

  // A document that is still being made when the conversation is left is not saved, which would be a surprise
  useEffect(() => () => running.current?.abort(), []);

  async function save(format: ExportFormat) {
    // Only one at a time: the server does the work, and a second would be a second file
    if (running.current) return;
    const controller = new AbortController();
    running.current = controller;
    setSaving(format);
    onProblem(null);
    try {
      const { file, name } = await api.exportChat(id, format, controller.signal);
      saveFile(file, name);
    } catch (error) {
      // A request given up because the conversation was left did not fail, so there is nothing to tell of
      if (!controller.signal.aborted) {
        report(error);
        onProblem(problemOf(error));
      }
    } finally {
      running.current = null;
      setSaving(null);
    }
  }

  return { saving, save };
}
