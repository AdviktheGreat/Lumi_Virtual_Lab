"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

// How close to the bottom still counts as being at it, in pixels, which a fraction of a line scrolled is within
const NEAR_BOTTOM = 48;

// Keeps a scrolling list at its end as it grows, for as long as the reader has not scrolled up from it
export function useStickToBottom<T extends HTMLElement>(change: unknown) {
  const scroller = useRef<T>(null);
  const stuck = useRef(true);
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
    stuck.current = near;
    setAtBottom(near);
  }, []);

  useLayoutEffect(() => {
    const element = scroller.current;
    if (element !== null && stuck.current) element.scrollTo({ top: element.scrollHeight });
  }, [change]);

  // What is above the end growing, as an image loads or a block opens, leaves a reader at the end where they were
  useEffect(() => {
    const element = scroller.current;
    if (element === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stuck.current) element.scrollTo({ top: element.scrollHeight });
    });
    for (const child of Array.from(element.children)) observer.observe(child);

    return () => observer.disconnect();
  }, []);

  return { scroller, atBottom, jump, onScroll };
}
