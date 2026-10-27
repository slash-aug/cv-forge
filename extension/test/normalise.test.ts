import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { normaliseQuestion } from "../src/shared/normalise";

const table: { question: string; key: string }[] = JSON.parse(
  readFileSync(resolve(__dirname, "../../tests/fixtures/normalise_table.json"), "utf8"),
);

test("table has rows", () => expect(table.length).toBe(19));

for (const row of table)
  test(`normalises ${JSON.stringify(row.question)}`, () => {
    expect(normaliseQuestion(row.question)).toBe(row.key);
  });

test("sharp s folds like casefold", () => {
  expect(normaliseQuestion("Straße")).toBe("strasse");
});
