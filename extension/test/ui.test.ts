import { describe, expect, test } from "vitest";
import { isFramed } from "../src/content/ui";

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
