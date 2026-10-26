import { expect, test } from "vitest";
import { pickDescription } from "../src/fill/variants";

const desc = { "200": "a".repeat(150), "500": "b".repeat(400), "1000": "c".repeat(900), "2000": "d".repeat(1500) };

test.each([
  [null, "d".repeat(1500)],
  [600, "b".repeat(400)],
  [150, "a".repeat(150)],
  [100, ""],
  [1000, "c".repeat(900)],
])("pickDescription(%s)", (max, expected) => {
  expect(pickDescription(desc, max)).toBe(expected);
});

test("skips empty variants", () => {
  expect(pickDescription({ "200": "", "500": "", "1000": "x", "2000": "" }, 5000)).toBe("x");
});
