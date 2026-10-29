import { beforeEach, describe, expect, test, vi } from "vitest";
import { actionButton } from "../src/popup/action";

describe("actionButton", () => {
  let button: HTMLButtonElement;
  let status: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = `<button id="b">Mark applied</button><p id="s"></p>`;
    button = document.getElementById("b") as HTMLButtonElement;
    status = document.getElementById("s") as HTMLElement;
  });

  test("one click runs the action and shows its result", async () => {
    const action = vi.fn(async () => "Marked x as applied");
    actionButton(button, status, action);
    button.click();
    await vi.waitFor(() => expect(status.textContent).toBe("Marked x as applied"));
    expect(action).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(false);
  });

  test("the button is disabled while the action runs", async () => {
    let finish: (v: string) => void = () => undefined;
    actionButton(button, status, () => new Promise<string>((r) => (finish = r)));
    button.click();
    expect(button.disabled).toBe(true);
    finish("done");
    await vi.waitFor(() => expect(button.disabled).toBe(false));
  });
});
