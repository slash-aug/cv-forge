import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, expect, test, vi } from "vitest";
import { Api } from "../src/background/api";
import { createHandler } from "../src/background/main";

function area() {
  const data: Record<string, unknown> = {};
  return {
    data,
    get: async (key: string) => (key in data ? { [key]: data[key] } : {}),
    set: async (items: Record<string, unknown>) => void Object.assign(data, items),
    remove: async (key: string) => void delete data[key],
  };
}
let local: ReturnType<typeof area>;
let session: ReturnType<typeof area>;
let removed: ((id: number) => void) | undefined;

beforeEach(() => {
  local = area();
  session = area();
  removed = undefined;
  vi.stubGlobal("chrome", {
    storage: { local, session },
    tabs: { onRemoved: { addListener: (f: (id: number) => void) => (removed = f) } },
  });
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const job = (slug: string) => ({ slug, company: "C", role: "R", posting_url: null, apply_url: null });

function setup(fetchFn: typeof fetch) {
  local.data.token = "tok";
  const api = new Api(fetchFn, async () => ((await chrome.storage.local.get("token")).token as string) ?? null);
  return createHandler(api);
}

test("matchTab on linkedin never calls fetch", async () => {
  const f = vi.fn();
  const r = await setup(f)({ type: "matchTab", url: "https://www.linkedin.com/jobs/view/1", tabId: 1 });
  expect(r).toEqual({ ok: false, error: { kind: "linkedin" } });
  expect(f).not.toHaveBeenCalled();
});

test("remembered tab choice wins over server match", async () => {
  const f = vi.fn().mockImplementation(async () => json({ slugs: ["a"] }));
  const h = setup(f);
  await h({ type: "chooseJob", tabId: 7, slug: "b" });
  expect(session.data["tab:7"]).toBe("b");
  const r = await h({ type: "matchTab", url: "https://x.example/1", tabId: 7 });
  expect(r).toEqual({ ok: true, value: { slug: "b", candidates: [] } });
  expect(f).not.toHaveBeenCalled();
});

test("server match with one candidate picks it", async () => {
  const f = vi.fn().mockImplementation(async (url: string) =>
    String(url).includes("/match") ? json({ slugs: ["a"] }) : json([job("a"), job("b")]));
  const r = await setup(f)({ type: "matchTab", url: "https://x.example/1", tabId: 2 });
  expect(r).toEqual({ ok: true, value: { slug: "a", candidates: [job("a")] } });
});

test("server match with several candidates picks none", async () => {
  const f = vi.fn().mockImplementation(async (url: string) =>
    String(url).includes("/match") ? json({ slugs: ["a", "b"] }) : json([job("a"), job("b")]));
  const r = await setup(f)({ type: "matchTab", url: "https://x.example/1", tabId: 2 });
  expect(r).toEqual({ ok: true, value: { slug: null, candidates: [job("a"), job("b")] } });
});

test("setToken stores the token", async () => {
  const r = await setup(vi.fn())({ type: "setToken", token: " abc \n" });
  expect(r.ok).toBe(true);
  expect(local.data.token).toBe("abc");
});

test("tab choice is cleared when the tab closes", async () => {
  const { registerTabCleanup } = await import("../src/background/main");
  registerTabCleanup();
  session.data["tab:9"] = "a";
  removed?.(9);
  await Promise.resolve();
  expect(session.data["tab:9"]).toBeUndefined();
});

test("storage rejection becomes an internal error", async () => {
  const h = setup(vi.fn());
  session.get = async () => { throw new Error("boom"); };
  const r = await h({ type: "matchTab", url: "https://x.example/1", tabId: 1 });
  expect(r).toEqual({ ok: false, error: { kind: "internal" } });
});

test("unknown message type is an internal error", async () => {
  const r = await setup(vi.fn())({ type: "nope" } as never);
  expect(r).toEqual({ ok: false, error: { kind: "internal" } });
});

test("malformed /jobs body is an http error", async () => {
  for (const body of [{ a: 1 }, [{ slug: 1, company: "c", role: "r" }], [null]]) {
    const r = await setup(vi.fn().mockImplementation(async () => json(body)))({ type: "jobs" });
    expect(r).toEqual({ ok: false, error: { kind: "http", status: 200, body: null } });
  }
});

test("malformed /match body is an http error", async () => {
  for (const body of [{}, { slugs: "a" }, { slugs: [1] }]) {
    const r = await setup(vi.fn().mockImplementation(async () => json(body)))({ type: "matchTab", url: "https://x.example/1", tabId: 1 });
    expect(r).toEqual({ ok: false, error: { kind: "http", status: 200, body: null } });
  }
});

test("pdf message carries base64, not an ArrayBuffer", async () => {
  const kit = { ...JSON.parse(readFileSync(resolve(__dirname, "fixtures/kit.json"), "utf8")) };
  const f = vi.fn().mockImplementation(async (url: string) =>
    String(url).endsWith("/kit/s") ? json(kit) : new Response(new Uint8Array([1, 2, 3])));
  const r = await setup(f)({ type: "pdf", slug: "s", which: "cv" });
  expect(r).toEqual({ ok: true, value: { name: "cv.pdf", base64: "AQID" } });
});

test("content-script sender cannot set or read another tab's choice", async () => {
  const f = vi.fn().mockImplementation(async (url: string) =>
    String(url).includes("/match") ? json({ slugs: [] }) : json([]));
  const h = setup(f);
  await h({ type: "chooseJob", tabId: 99, slug: "evil" }, 5);
  expect(session.data["tab:99"]).toBeUndefined();
  expect(session.data["tab:5"]).toBe("evil");
  session.data["tab:99"] = "secret";
  const r = await h({ type: "matchTab", url: "https://x.example/1", tabId: 99 }, 6);
  expect(r.ok && (r.value as { slug: string | null }).slug).toBeNull();
});
