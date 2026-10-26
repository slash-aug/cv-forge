import { expect, test } from "vitest";
import { fromBase64, toBase64 } from "../src/shared/bytes";

test("base64 round-trips every byte value", () => {
  const bytes = new Uint8Array(256).map((_, i) => i);
  const out = new Uint8Array(fromBase64(toBase64(bytes.buffer)));
  expect(out).toEqual(bytes);
});

test("base64 round-trips a large buffer and empty", () => {
  const big = new Uint8Array(100_000).map((_, i) => i % 251);
  expect(new Uint8Array(fromBase64(toBase64(big.buffer)))).toEqual(big);
  expect(fromBase64(toBase64(new ArrayBuffer(0))).byteLength).toBe(0);
});
