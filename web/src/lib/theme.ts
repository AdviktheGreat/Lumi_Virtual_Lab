import { useSyncExternalStore } from "react";
import { THEME_KEY as KEY } from "./theme-script";

export type Theme = "light" | "dark" | "system";

const CHANGED = "vl-theme-changed";

function stored(): Theme {
  try {
    const value = localStorage.getItem(KEY);

    return value === "light" || value === "system" ? value : "dark";
  } catch {
    return "dark";
  }
}

function apply(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // A browser that keeps nothing still shows the theme chosen, until the page is closed
  }
  apply(theme);
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(onChange: () => void): () => void {
  const colors = matchMedia("(prefers-color-scheme: dark)");
  // Another tab choosing a theme, or the system changing between light and dark, which only a page left to the
  // system follows
  const follow = () => {
    apply(stored());
    onChange();
  };
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", follow);
  colors.addEventListener("change", follow);

  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", follow);
    colors.removeEventListener("change", follow);
  };
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, stored, () => "dark");
}
