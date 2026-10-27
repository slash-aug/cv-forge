import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { KitShapeError, KitVersionError, parseKit } from "../src/shared/kit";

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

test("array keys must be arrays", () => {
  for (const key of ["fields", "work", "education", "languages", "certificates", "answers", "tracker"]) {
    expect(() => parseKit({ ...raw(), [key]: {} }), key).toThrow(KitShapeError);
    expect(() => parseKit({ ...raw(), [key]: null }), key).toThrow(KitShapeError);
  }
});

test("object-or-null keys are checked", () => {
  for (const key of ["salary", "recruiter_note", "email"]) {
    expect(() => parseKit({ ...raw(), [key]: "x" }), key).toThrow(KitShapeError);
    expect(() => parseKit({ ...raw(), [key]: [] }), key).toThrow(KitShapeError);
  }
  expect(() => parseKit({ ...raw(), links: null })).toThrow(KitShapeError);
  expect(() => parseKit({ ...raw(), links: [] })).toThrow(KitShapeError);
  const missing = raw();
  delete missing.fields;
  expect(() => parseKit(missing)).toThrow(KitShapeError);
});

test("errors name the slug when given", () => {
  expect(() => parseKit({ ...raw(), schema_version: 1 }, "acme-dev")).toThrow(
    "Kit is from an older cv-forge. Rerun: cvforge kit acme-dev",
  );
  expect(() => parseKit({ ...raw(), fields: 1 }, "acme-dev")).toThrow("Kit is malformed. Rerun: cvforge kit acme-dev");
});

test("shape error message", () => {
  expect(() => parseKit({ ...raw(), fields: 1 })).toThrow("Kit is malformed. Rerun: cvforge kit <slug>");
});

test("null recruiter_note and email are fine", () => {
  const kit = parseKit({ ...raw(), recruiter_note: null, email: null });
  expect(kit.email).toBeNull();
});
