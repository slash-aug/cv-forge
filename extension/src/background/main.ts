import { isLinkedInHost } from "../shared/linkedin";
import type { Job, Match, Msg, Result } from "../shared/messages";
import { Api } from "./api";

const tabKey = (tabId: number) => `tab:${tabId}`;

async function getToken(): Promise<string | null> {
  const stored = (await chrome.storage.local.get("token")).token;
  return typeof stored === "string" && stored ? stored : null;
}

async function matchTab(api: Api, m: Extract<Msg, { type: "matchTab" }>, senderTabId?: number): Promise<Result<Match>> {
  let host: string;
  try {
    host = new URL(m.url).hostname;
  } catch {
    return { ok: false, error: { kind: "http", status: 400, body: { error: "bad-url" } } };
  }
  if (isLinkedInHost(host)) return { ok: false, error: { kind: "linkedin" } };

  const tabId = m.tabId ?? senderTabId;
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

/** Maps every message to a Result; the only code path that talks to the server. */
export function createHandler(api: Api) {
  return async (msg: Msg, senderTabId?: number): Promise<Result<unknown>> => {
    switch (msg.type) {
      case "status":
        return api.health();
      case "jobs":
        return api.jobs();
      case "matchTab":
        return matchTab(api, msg, senderTabId);
      case "chooseJob":
        await chrome.storage.session.set({ [tabKey(msg.tabId)]: msg.slug });
        return { ok: true, value: null };
      case "kit":
        return api.kit(msg.slug);
      case "pdf":
        return api.pdf(msg.slug, msg.which);
      case "bank":
        return api.bank(msg.q, msg.lang);
      case "saveAnswer":
        return api.saveAnswer(msg.slug, msg.question, msg.answer);
      case "markApplied":
        return api.markApplied(msg.slug);
      case "setToken":
        await chrome.storage.local.set({ token: msg.token.trim() });
        return { ok: true, value: null };
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
    handle(msg, sender.tab?.id).then(sendResponse);
    return true;
  });
  registerTabCleanup();
}

if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) start();
