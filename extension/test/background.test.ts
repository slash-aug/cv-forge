import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, expect, test, vi } from "vitest";
import { Api } from "../src/background/api";
import { createHandler } from "../src/background/main";
import { siteOf } from "../src/background/site";

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

// /match answers `slugs`; /jobs lists every open job.
const server = (slugs: string[], open = ["a", "b"]) =>
  vi.fn().mockImplementation(async (url: string) =>
    String(url).includes("/match") ? json({ slugs }) : json(open.map(job)));

test("siteOf keeps the last two labels, three for a ccTLD second level", () => {
  expect(siteOf("boards.example.com")).toBe("example.com");
  expect(siteOf("example.com")).toBe("example.com");
  expect(siteOf("vagas.example.com.br")).toBe("example.com.br");
  expect(siteOf("jobs.example.co.uk")).toBe("example.co.uk");
  expect(siteOf("empresa.gupy.io")).toBe("gupy.io");
  expect(siteOf("Login.Gupy.IO.")).toBe("gupy.io");
});

test("chooseJob remembers the slug with the page's site", async () => {
  const h = setup(server([]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://jobs.example.com/1" });
  expect(session.data["tab:7"]).toEqual({ slug: "b", site: "example.com" });
});

test("remembered choice is reused on the same site", async () => {
  const h = setup(server([]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://jobs.example.com/1" });
  const r = await h({ type: "matchTab", url: "https://apply.example.com/form", tabId: 7 });
  expect(r).toEqual({ ok: true, value: { slug: "b", candidates: [job("b")] } });
});

test("remembered choice is not reused on another site", async () => {
  const h = setup(server([]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://jobs.example.com/1" });
  const r = await h({ type: "matchTab", url: "https://careers.other.test/form", tabId: 7 });
  expect(r).toEqual({ ok: true, value: { slug: null, candidates: [] } });
  expect(session.data["tab:7"]).toEqual({ slug: "b", site: "example.com" });
});

test("a unique server match for a different job wins and replaces the memory", async () => {
  const h = setup(server(["a"]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://jobs.example.com/1" });
  const r = await h({ type: "matchTab", url: "https://jobs.example.com/2", tabId: 7 });
  expect(r).toEqual({ ok: true, value: { slug: "a", candidates: [job("a")] } });
  expect(session.data["tab:7"]).toEqual({ slug: "a", site: "example.com" });
});

test("several server matches do not override the memory on the same site", async () => {
  const h = setup(server(["a", "b"]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://jobs.example.com/1" });
  const r = await h({ type: "matchTab", url: "https://jobs.example.com/2", tabId: 7 });
  expect(r.ok && (r.value as { slug: string | null }).slug).toBe("b");
});

test("a remembered slug that is no longer open is dropped", async () => {
  const h = setup(server([], ["a"]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://jobs.example.com/1" });
  const r = await h({ type: "matchTab", url: "https://jobs.example.com/1", tabId: 7 });
  expect(r).toEqual({ ok: true, value: { slug: null, candidates: [] } });
  expect(session.data["tab:7"]).toBeUndefined();
});

test("Gupy: a choice on the company host is reused on the login host", async () => {
  const h = setup(server([]));
  await h({ type: "chooseJob", tabId: 7, slug: "b", url: "https://empresa.gupy.io/jobs/1" });
  const r = await h({ type: "matchTab", url: "https://login.gupy.io/candidates/apply", tabId: 7 });
  expect(r.ok && (r.value as { slug: string | null }).slug).toBe("b");
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
  const h = setup(server([]));
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
  await h({ type: "chooseJob", tabId: 99, slug: "evil", url: "https://x.example/1" }, 5);
  expect(session.data["tab:99"]).toBeUndefined();
  expect(session.data["tab:5"]).toEqual({ slug: "evil", site: "x.example" });
  session.data["tab:99"] = { slug: "secret", site: "x.example" };
  const r = await h({ type: "matchTab", url: "https://x.example/1", tabId: 99 }, 6);
  expect(r.ok && (r.value as { slug: string | null }).slug).toBeNull();
});
