import { describe, expect, test } from "vitest";
import { dockPosition, isFramed } from "../src/content/ui";

describe("isFramed", () => {
  test("a top-level page is not framed", () => {
    expect(isFramed(window)).toBe(false);
  });

  test("a window whose top is another window is framed", () => {
    const fake = { top: {} } as unknown as Window;
    expect(isFramed(fake)).toBe(true);
  });

  test("a window whose top cannot be read is framed", () => {
    const fake = Object.defineProperty({}, "top", {
      get() {
        throw new Error("blocked");
      },
    }) as unknown as Window;
    expect(isFramed(fake)).toBe(true);
  });
});

describe("dockPosition", () => {
  test("a top-level page pins the dock to the bottom-right of the screen", () => {
    expect(dockPosition(false)).toEqual({ position: "fixed", top: "auto", bottom: "16px" });
  });

  // A tall embedded form (MongoDB's Greenhouse embed) stretches the frame, so its
  // bottom-right corner is the end of the form: put the dock at the form's top instead.
  test("a framed form puts the dock at the top of the frame", () => {
    expect(dockPosition(true)).toEqual({ position: "absolute", top: "16px", bottom: "auto" });
  });
});
