import { describe, expect, it, vi } from "vitest";
import { returnFocusTo } from "./focus";

function opener(isConnected: boolean) {
  return { isConnected, focus: vi.fn() } as unknown as HTMLElement & { focus: ReturnType<typeof vi.fn> };
}

describe("returning the focus when a dialog closes", () => {
  it("gives it to what opened the dialog, and keeps the dialog from giving it to anything else", () => {
    const from = opener(true);
    const event = { preventDefault: vi.fn() };

    returnFocusTo(from)(event as unknown as Event);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(from.focus).toHaveBeenCalledOnce();
  });

  it("gives it to nothing when what opened the dialog has gone from the page", () => {
    const from = opener(false);
    const event = { preventDefault: vi.fn() };

    returnFocusTo(from)(event as unknown as Event);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(from.focus).not.toHaveBeenCalled();
  });

  it("gives it to nothing when nothing opened the dialog", () => {
    const event = { preventDefault: vi.fn() };

    expect(() => returnFocusTo(null)(event as unknown as Event)).not.toThrow();
    expect(event.preventDefault).toHaveBeenCalledOnce();
  });
});
