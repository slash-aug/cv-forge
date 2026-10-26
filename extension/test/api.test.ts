import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, vi } from "vitest";
import { Api } from "../src/background/api";
import { errorText } from "../src/shared/messages";

const kitRaw = () => JSON.parse(readFileSync(resolve(__dirname, "fixtures/kit.json"), "utf8"));
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const api = (fetchFn: typeof fetch, token: string | null = "tok") => new Api(fetchFn, async () => token);

test("network failure is down", async () => {
  const r = await api(vi.fn().mockRejectedValue(new TypeError("fail"))).health();
  expect(r).toEqual({ ok: false, error: { kind: "down" } });
});

test("401 is token", async () => {
  const r = await api(vi.fn().mockResolvedValue(json({ error: "token" }, 401))).jobs();
  expect(r).toEqual({ ok: false, error: { kind: "token" } });
});

test("missing token is token and sends nothing", async () => {
  const f = vi.fn();
  const r = await api(f, null).health();
  expect(r).toEqual({ ok: false, error: { kind: "token" } });
  expect(f).not.toHaveBeenCalled();
});

test("every request carries X-CVForge-Token and targets 127.0.0.1", async () => {
  const f = vi.fn().mockImplementation(async () => json({}));
  const a = api(f);
  await a.health();
  await a.jobs();
  await a.match("https://x.example/a", "greenhouse", "9");
  await a.bank("why us", "en");
  await a.saveAnswer("s", "q", "a");
  await a.markApplied("s");
  expect(f).toHaveBeenCalledTimes(6);
  for (const [url, init] of f.mock.calls) {
    expect(String(url).startsWith("http://127.0.0.1:47321/")).toBe(true);
    expect(new Headers(init.headers).get("X-CVForge-Token")).toBe("tok");
  }
  expect(String(f.mock.calls[2][0])).toContain("url=https%3A%2F%2Fx.example%2Fa");
  expect(String(f.mock.calls[2][0])).toContain("job_id=9");
  expect(f.mock.calls[4][1].method).toBe("POST");
  expect(JSON.parse(f.mock.calls[4][1].body)).toEqual({ question: "q", answer: "a" });
});

test("kit parses", async () => {
  const r = await api(vi.fn().mockResolvedValue(json(kitRaw()))).kit("s");
  expect(r.ok && r.value.slug).toBe(kitRaw().slug);
});

test("kit with schema 1 is an error, not a throw", async () => {
  const r = await api(vi.fn().mockResolvedValue(json({ ...kitRaw(), schema_version: 1 }))).kit("s");
  expect(r).toEqual({
    ok: false,
    error: { kind: "kit", message: "Kit is from an older cv-forge. Rerun: cvforge kit <slug>" },
  });
});

test("malformed kit is a kit error", async () => {
  const r = await api(vi.fn().mockResolvedValue(json({ ...kitRaw(), fields: 3 }))).kit("s");
  expect(r.ok === false && r.error.kind).toBe("kit");
});

test("403 linkedin maps to linkedin, other 403 stays http", async () => {
  const a = api(vi.fn().mockResolvedValueOnce(json({ error: "linkedin" }, 403)).mockResolvedValueOnce(json({ error: "origin" }, 403)));
  expect(await a.match("https://x.example")).toEqual({ ok: false, error: { kind: "linkedin" } });
  expect(await a.match("https://x.example")).toEqual({
    ok: false,
    error: { kind: "http", status: 403, body: { error: "origin" } },
  });
});

test("422 audit keeps its body", async () => {
  const body = { error: "audit", findings: [{ kind: "number", ref: "9", message: "m" }] };
  const r = await api(vi.fn().mockResolvedValue(json(body, 422))).saveAnswer("s", "q", "a");
  expect(r).toEqual({ ok: false, error: { kind: "http", status: 422, body } });
});

test("pdf uses the kit link basename and returns bytes", async () => {
  const f = vi.fn().mockImplementation(async (url: string) =>
    String(url).endsWith("/kit/s") ? json(kitRaw()) : new Response(new Uint8Array([1, 2, 3])));
  const r = await api(f).pdf("s", "cv");
  expect(r.ok).toBe(true);
  if (r.ok) {
    expect(r.value.name).toBe("cv.pdf");
    expect(new Uint8Array(r.value.bytes)).toEqual(new Uint8Array([1, 2, 3]));
  }
  expect(String(f.mock.calls[1][0])).toBe("http://127.0.0.1:47321/kit/s/cv.pdf");
});

test("pdf with no link in the kit is a 404 http error", async () => {
  const r = await api(vi.fn().mockResolvedValue(json(kitRaw()))).pdf("s", "letter");
  expect(r).toEqual({ ok: false, error: { kind: "http", status: 404, body: { error: "no-pdf" } } });
});

test("errorText texts", () => {
  expect(errorText({ kind: "down" })).toBe("cv-forge server not running: run .venv/bin/cvforge serve");
  expect(errorText({ kind: "token" })).toBe("Pairing token rejected: paste the token from cvforge serve --show-token");
  expect(errorText({ kind: "linkedin" })).toBe("cv-forge does not run on LinkedIn");
  expect(errorText({ kind: "http", status: 500, body: null })).toBe("Server error 500");
  expect(errorText({ kind: "internal" })).toBe("cv-forge extension error: reload the extension");
  expect(errorText({ kind: "kit", message: "boom" })).toBe("boom");
});
