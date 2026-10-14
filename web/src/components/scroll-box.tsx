"use client";

import { useEffect, useRef, useState, type ComponentProps } from "react";
import { cn } from "@/lib/utils";

// How much more than a box shows it may hold before it is said to scroll, since a size that is rounded can be a pixel
// short of what is in it
const SLACK_PX = 1;

// A box that scrolls, and that a keyboard can reach when it does, since the arrow keys scroll only what has the focus, and
// without it what is out of sight cannot be read. A box that does not scroll is left out of the order of the page, where
// it would be one more stop for nothing, which is what every block of code would be.
export function ScrollBox({ as = "div", className, children, ...props }: ComponentProps<"div"> & { as?: "div" | "pre" }) {
  const box = useRef<HTMLDivElement>(null);
  const [scrolls, setScrolls] = useState(false);
  // A pre takes what a div does and is a box in the same way, which the types of the two do not say
  const Tag = as as "div";

  function measure() {
    const element = box.current;
    if (element) setScrolls(element.scrollHeight > element.clientHeight + SLACK_PX || element.scrollWidth > element.clientWidth + SLACK_PX);
  }

  // How much of what is in the box shows changes with the size of the box, which is the window's or what the page puts
  // around it, and with what is in it, which can change after it is drawn and leave the box the size it was: the text of
  // a file once it is read, or a line of code as it is written. Neither makes this component draw itself again.
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const resized = new ResizeObserver(measure);
    resized.observe(element);
    const changed = new MutationObserver(measure);
    changed.observe(element, { childList: true, subtree: true, characterData: true, attributes: true });

    return () => {
      resized.disconnect();
      changed.disconnect();
    };
  }, []);

  return (
    <Tag
      {...props}
      ref={box}
      tabIndex={scrolls ? 0 : undefined}
      className={cn("outline-none focus-visible:ring-3 focus-visible:ring-ring/50", className)}
    >
      {children}
    </Tag>
  );
}
