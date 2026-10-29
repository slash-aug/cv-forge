/**
 * A button that runs `action` on click and shows its result in `status`, so the popup
 * always says what happened (window.confirm closed the Firefox popup before it could).
 */
export function actionButton(button: HTMLButtonElement, status: HTMLElement, action: () => Promise<string>): void {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      status.textContent = await action();
    } finally {
      button.disabled = false;
    }
  });
}
