// What a dialog does as it closes: the focus goes back to what opened it, which is not done by Radix when nothing in the
// page is its trigger, and is not done at all if what opened it has gone since
export function returnFocusTo(opener: HTMLElement | null): (event: Event) => void {
  return (event) => {
    event.preventDefault();
    if (opener?.isConnected) opener.focus();
  };
}
