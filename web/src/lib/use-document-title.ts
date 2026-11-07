import { useEffect } from "react";

export const BASE_TITLE = "Lumi Virtual Lab";

// The title of the tab for as long as the page that asks is shown: the name given, then the lab's. Next writes the title again
// as a page opens, which for a page whose name is known the moment it opens is after it was written here, so it is written
// again whenever the title is changed by anything else, until the page goes.
export function useDocumentTitle(name: string | null | undefined): void {
  useEffect(() => {
    const wanted = name ? `${name} · ${BASE_TITLE}` : BASE_TITLE;
    const keep = () => {
      if (document.title !== wanted) document.title = wanted;
    };
    keep();
    const watcher = new MutationObserver(keep);
    watcher.observe(document.head, { childList: true, subtree: true, characterData: true });

    return () => {
      watcher.disconnect();
      // Left as it is if the page that follows has written its own, which is not this page's to take back
      if (document.title === wanted) document.title = BASE_TITLE;
    };
  }, [name]);
}
