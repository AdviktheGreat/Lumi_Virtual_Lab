"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

// How close to the bottom still counts as being at it, in pixels, which a fraction of a line scrolled is within
const NEAR_BOTTOM = 48;

// Whether a list that has just grown is still to be kept at its end. A reader who scrolled up is only told of by a
// scroll event a moment after, and the list may have grown before it, so where the list is now is looked at as well: it
// is above where it was last said to be, and not at the end, if the reader has moved up.
export function followsEnd(stuck: boolean, now: { top: number; gap: number }, seenTop: number): boolean {
  if (!stuck) return false;

  return now.gap <= NEAR_BOTTOM || now.top >= seenTop - 1;
}

// Keeps a scrolling list at its end as it grows, for as long as the reader has not scrolled up from it
export function useStickToBottom<T extends HTMLElement>(change: unknown) {
  const scroller = useRef<T>(null);
  const stuck = useRef(true);
  // Where the list was last said to be scrolled to, or was scrolled to
  const seenTop = useRef(0);
  const [atBottom, setAtBottom] = useState(true);

  const jump = useCallback((behavior: ScrollBehavior = "smooth") => {
    const element = scroller.current;
    if (element === null) return;
    stuck.current = true;
    setAtBottom(true);
    element.scrollTo({ top: element.scrollHeight, behavior });
  }, []);

  const onScroll = useCallback(() => {
    const element = scroller.current;
    if (element === null) return;
    const near = element.scrollHeight - element.scrollTop - element.clientHeight <= NEAR_BOTTOM;
    seenTop.current = element.scrollTop;
    stuck.current = near;
    setAtBottom(near);
  }, []);

  const follow = useCallback((element: T) => {
    const now = { top: element.scrollTop, gap: element.scrollHeight - element.scrollTop - element.clientHeight };
    if (!followsEnd(stuck.current, now, seenTop.current)) {
      stuck.current = false;

      return;
    }
    element.scrollTo({ top: element.scrollHeight });
    seenTop.current = element.scrollTop;
  }, []);

  useLayoutEffect(() => {
    const element = scroller.current;
    if (element !== null && stuck.current) follow(element);
  }, [change, follow]);

  // What is above the end growing, as an image loads or a block opens, leaves a reader at the end where they were
  useEffect(() => {
    const element = scroller.current;
    if (element === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stuck.current) follow(element);
    });
    for (const child of Array.from(element.children)) observer.observe(child);

    return () => observer.disconnect();
  }, [follow]);

  return { scroller, atBottom, jump, onScroll };
}
