import { isLinkedInHost } from "../shared/linkedin";
import type { Job, Match, Msg, Result } from "../shared/messages";
import { toBase64 } from "../shared/bytes";
import { Api } from "./api";

const tabKey = (tabId: number) => `tab:${tabId}`;

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

  if (tabId !== undefined) {
    const remembered = (await chrome.storage.session.get(tabKey(tabId)))[tabKey(tabId)];
    if (typeof remembered === "string") return { ok: true, value: { slug: remembered, candidates: [] } };
  }
  const slugs = await api.match(m.url, m.site, m.jobId);
  if (!slugs.ok) return slugs;
  const jobs = await api.jobs();
  if (!jobs.ok) return jobs;
  const candidates: Job[] = jobs.value.filter((j) => slugs.value.includes(j.slug));
  return { ok: true, value: { slug: candidates.length === 1 ? candidates[0].slug : null, candidates } };
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
        await chrome.storage.session.set({ [tabKey(senderTabId ?? msg.tabId)]: msg.slug });
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
