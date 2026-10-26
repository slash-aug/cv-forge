import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { KitVersionError, parseKit } from "../src/shared/kit";

const raw = () => JSON.parse(readFileSync(resolve(__dirname, "fixtures/kit.json"), "utf8"));

test("fixture parses", () => {
  const kit = parseKit(raw());
  expect(kit.schema_version).toBe(2);
  expect(kit.email).toBeNull();
  expect(kit.fields.length).toBeGreaterThan(0);
});

test("schema 1 throws KitVersionError", () => {
  const old = { ...raw(), schema_version: 1 };
  expect(() => parseKit(old)).toThrow(KitVersionError);
  expect(() => parseKit(old)).toThrow("Kit is from an older cv-forge. Rerun: cvforge kit <slug>");
});

test("non-object throws", () => {
  expect(() => parseKit(null)).toThrow(KitVersionError);
  expect(() => parseKit("x")).toThrow(KitVersionError);
});

test("salary null is fine", () => {
  const kit = parseKit({ ...raw(), salary: null });
  expect(kit.salary).toBeNull();
});
