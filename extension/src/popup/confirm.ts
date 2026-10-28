const CONFIRM = "Click again to confirm";
const LAPSE_MS = 4000;

/**
 * A button that runs `action` on a second click and shows its result in `status`.
 * Replaces window.confirm, which closes the Firefox popup before the result shows.
 */
export function twoStep(button: HTMLButtonElement, status: HTMLElement, action: () => Promise<string>): void {
  const label = button.textContent ?? "";
  let armed = false;
  let lapse: ReturnType<typeof setTimeout> | undefined;
  const reset = (): void => {
    armed = false;
    clearTimeout(lapse);
    button.textContent = label;
  };
  button.addEventListener("click", async () => {
    if (!armed) {
      armed = true;
      button.textContent = CONFIRM;
      lapse = setTimeout(reset, LAPSE_MS);
      return;
    }
    reset();
    button.disabled = true;
    try {
      status.textContent = await action();
    } finally {
      button.disabled = false;
    }
  });
}
