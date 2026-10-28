import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { twoStep } from "../src/popup/confirm";

describe("twoStep", () => {
  let button: HTMLButtonElement;
  let status: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = `<button id="b">Mark applied</button><p id="s"></p>`;
    button = document.getElementById("b") as HTMLButtonElement;
    status = document.getElementById("s") as HTMLElement;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("the first click asks for confirmation and does not run the action", () => {
    const action = vi.fn(async () => "done");
    twoStep(button, status, action);
    button.click();
    expect(action).not.toHaveBeenCalled();
    expect(button.textContent).toBe("Click again to confirm");
  });

  test("the second click runs the action and shows its result", async () => {
    const action = vi.fn(async () => "Marked as applied");
    twoStep(button, status, action);
    button.click();
    button.click();
    await vi.runAllTimersAsync();
    expect(action).toHaveBeenCalledTimes(1);
    expect(status.textContent).toBe("Marked as applied");
    expect(button.textContent).toBe("Mark applied");
    expect(button.disabled).toBe(false);
  });

  test("the confirmation lapses after a few seconds", async () => {
    const action = vi.fn(async () => "done");
    twoStep(button, status, action);
    button.click();
    await vi.advanceTimersByTimeAsync(5000);
    expect(button.textContent).toBe("Mark applied");
    button.click();
    expect(action).not.toHaveBeenCalled();
  });
});
