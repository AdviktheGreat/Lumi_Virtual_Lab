"use client";

import { useRef, useState } from "react";
import { api } from "./api";
import { describeError } from "./errors";
import type { McpChange, McpServer } from "./types";

export interface McpChanges {
  // What went wrong with the last change, and what came of it, if either
  problem: string | null;
  done: string | null;
  setProblem: (problem: string | null) => void;
  setDone: (done: string | null) => void;
  // The servers as they were chosen, which a box shows at once, and not yet as the server has kept them
  shown: (servers: McpServer[]) => McpServer[];
  change: (name: string, what: McpChange) => void;
  // Another change to the servers, made after those asked for before it and before those asked for after, so that the list it
  // gives back is not replaced by one that was asked for before it
  serial: (task: () => Promise<void>) => void;
  // What a key that was given or taken away changes is what the server says it is missing
  refresh: () => Promise<void>;
  signOut: (server: McpServer) => Promise<void>;
  remove: (server: McpServer) => Promise<void>;
}

// What is done to the MCP servers that are set up: turning them on and off, choosing how they are signed in to, signing out of
// them, and taking them away. Each change is kept as it is chosen, and what the server gives back is what is shown from then on.
export function useMcpChanges(onChanged: (servers: McpServer[]) => void, report: (error: unknown) => void): McpChanges {
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // What was chosen and is not yet kept, shown as it was chosen so that a box answers at once, until every change has been
  // answered, and then what the server holds is what is shown, whether it kept them or not
  const [chosen, setChosen] = useState<Record<string, McpChange>>({});
  // The changes are made one after another, so that the list each gives back is not replaced by one that was asked for
  // before it and answered after
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);

  function change(name: string, what: McpChange) {
    waiting.current += 1;
    setChosen((was) => ({ ...was, [name]: { ...was[name], ...what } }));
    queue.current = queue.current.then(async () => {
      try {
        setProblem(null);
        setDone(null);
        onChanged(await api.changeMcpServer(name, what));
      } catch (error) {
        report(error);
        setProblem(describeError(error));
      } finally {
        waiting.current -= 1;
        if (waiting.current === 0) setChosen({});
      }
    });
  }

  function serial(task: () => Promise<void>) {
    queue.current = queue.current.then(task).catch(report);
  }

  async function refresh() {
    try {
      onChanged(await api.mcp());
    } catch (error) {
      report(error);
    }
  }

  async function signOut(server: McpServer) {
    setProblem(null);
    setDone(null);
    try {
      onChanged(await api.signOutMcpServer(server.name));
      setDone(`Signed out of ${server.title}. A program that has it on asks you to sign in again.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  async function remove(server: McpServer) {
    setProblem(null);
    setDone(null);
    try {
      onChanged(await api.removeMcpServer(server.name));
      setDone(`Removed ${server.name}.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  function shown(servers: McpServer[]): McpServer[] {
    return servers.map((server) => (server.name in chosen ? { ...server, ...chosen[server.name] } : server));
  }

  return { problem, done, setProblem, setDone, shown, change, serial, refresh, signOut, remove };
}
