import { isLinkedInHost } from "../shared/linkedin";
import type { Job, Match, Msg, Result } from "../shared/messages";
import { toBase64 } from "../shared/bytes";
import { Api } from "./api";
import { siteOf } from "./site";

const tabKey = (tabId: number) => `tab:${tabId}`;

/** The job chosen in the popup, kept per tab and only for the site it was chosen on. */
interface Remembered {
  slug: string;
  site: string;
}

const isRemembered = (v: unknown): v is Remembered =>
  typeof v === "object" && v !== null &&
  typeof (v as Remembered).slug === "string" && typeof (v as Remembered).site === "string";

function siteOfUrl(url: string): string | null {
  try {
    return siteOf(new URL(url).hostname);
  } catch {
    return null;
  }
}

async function getToken(): Promise<string | null> {
  const stored = (await chrome.storage.local.get("token")).token;
  return typeof stored === "string" && stored ? stored : null;
}

async function matchTab(api: Api, m: Extract<Msg, { type: "matchTab" }>, tabId?: number): Promise<Result<Match>> {
  let host: string;
  try {
    host = new URL(m.url).hostname;
  } catch {
    return { ok: false, error: { kind: "http", status: 400, body: { error: "bad-url" } } };
  }
  if (isLinkedInHost(host)) return { ok: false, error: { kind: "linkedin" } };

  const slugs = await api.match(m.url, m.site, m.jobId);
  if (!slugs.ok) return slugs;
  const jobs = await api.jobs();
  if (!jobs.ok) return jobs;
  const candidates: Job[] = jobs.value.filter((j) => slugs.value.includes(j.slug));
  const unique = candidates.length === 1 ? candidates[0].slug : null;

  if (tabId !== undefined) {
    const key = tabKey(tabId);
    const stored = (await chrome.storage.session.get(key))[key];
    const remembered = isRemembered(stored) ? stored : null;
    const site = siteOf(host);
    if (remembered && !jobs.value.some((j) => j.slug === remembered.slug)) {
      await chrome.storage.session.remove(key);
    } else if (remembered && unique !== null && unique !== remembered.slug) {
      // the server names one other job for this page: that beats the popup choice
      await chrome.storage.session.set({ [key]: { slug: unique, site } satisfies Remembered });
    } else if (remembered && remembered.site === site) {
      return { ok: true, value: { slug: remembered.slug, candidates: jobs.value.filter((j) => j.slug === remembered.slug) } };
    }
  }
  return { ok: true, value: { slug: unique, candidates } };
}

const internal: Result<never> = { ok: false, error: { kind: "internal" } };

/**
 * Maps every message to a Result and never throws. A sender with a tab (content script)
 * only ever touches its own tab; the tabId in the message is honoured only from the popup.
 */
export function createHandler(api: Api) {
  const run = async (msg: Msg, senderTabId?: number): Promise<Result<unknown>> => {
    switch (msg.type) {
      case "status":
        return api.health();
      case "jobs":
        return api.jobs();
      case "matchTab":
        return matchTab(api, msg, senderTabId ?? msg.tabId);
      case "chooseJob": {
        const site = siteOfUrl(msg.url);
        if (site === null) return { ok: false, error: { kind: "http", status: 400, body: { error: "bad-url" } } };
        const remembered: Remembered = { slug: msg.slug, site };
        await chrome.storage.session.set({ [tabKey(senderTabId ?? msg.tabId)]: remembered });
        return { ok: true, value: null };
      }
      case "kit":
        return api.kit(msg.slug);
      case "pdf": {
        const r = await api.pdf(msg.slug, msg.which);
        return r.ok ? { ok: true, value: { name: r.value.name, base64: toBase64(r.value.bytes) } } : r;
      }
      case "bank":
        return api.bank(msg.q, msg.lang);
      case "saveAnswer":
        return api.saveAnswer(msg.slug, msg.question, msg.answer);
      case "markApplied":
        return api.markApplied(msg.slug);
      case "setToken":
        await chrome.storage.local.set({ token: msg.token.trim() });
        return { ok: true, value: null };
      default:
        return internal;
    }
  };
  return async (msg: Msg, senderTabId?: number): Promise<Result<unknown>> => {
    try {
      return await run(msg, senderTabId);
    } catch {
      return internal;
    }
  };
}

export function registerTabCleanup(): void {
  chrome.tabs.onRemoved.addListener((tabId) => {
    void chrome.storage.session.remove(tabKey(tabId));
  });
}

function start(): void {
  const handle = createHandler(new Api(fetch.bind(globalThis), getToken));
  chrome.runtime.onMessage.addListener((msg: Msg, sender, sendResponse) => {
    void handle(msg, sender.tab?.id).then(sendResponse, () => sendResponse({ ok: false, error: { kind: "internal" } }));
    return true;
  });
  registerTabCleanup();
}

if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) start();
