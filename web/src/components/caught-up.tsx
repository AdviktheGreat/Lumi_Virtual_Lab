"use client";

import { createContext, useContext } from "react";

// Whether the page has been told of everything that had happened in the conversation when it was opened. Until it has,
// what it is told is the conversation's past replayed, in pieces that come as they come, so that a call may be going on
// in it only because the end of the call has not come yet.
const CaughtUp = createContext(true);

export const CaughtUpProvider = CaughtUp.Provider;

export function useCaughtUp(): boolean {
  return useContext(CaughtUp);
}
