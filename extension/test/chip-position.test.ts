import { describe, expect, test } from "vitest";
import { chipPosition } from "../src/content/ui";

const chip = { width: 100, height: 30 };
const scroll = { x: 0, y: 500 };

describe("chipPosition keeps the chip inside the field", () => {
  test("one-line input: right end, vertically centred", () => {
    const at = chipPosition({ top: 100, left: 80, right: 680, height: 36 }, chip, scroll);
    expect(at).toEqual({ top: 603, left: 576 });
  });

  test("tall textarea: right end, near the top", () => {
    const at = chipPosition({ top: 100, left: 80, right: 780, height: 90 }, chip, scroll);
    expect(at).toEqual({ top: 604, left: 676 });
  });

  test("never starts left of the field", () => {
    const at = chipPosition({ top: 0, left: 80, right: 120, height: 36 }, chip, { x: 0, y: 0 });
    expect(at.left).toBe(80);
  });

  test("stays within the field's own rows, not below it", () => {
    const field = { top: 100, left: 0, right: 600, height: 36 };
    const at = chipPosition(field, chip, { x: 0, y: 0 });
    expect(at.top + chip.height).toBeLessThanOrEqual(field.top + field.height);
  });
});
