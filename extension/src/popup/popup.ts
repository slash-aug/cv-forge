import { errorText, type Job, type Match, type Msg, type Result } from "../shared/messages";
import { actionButton } from "./action";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

async function send<T>(msg: Msg): Promise<Result<T>> {
  try {
    const r = (await chrome.runtime.sendMessage(msg)) as Result<T> | undefined;
    return r ?? { ok: false, error: { kind: "internal" } };
  } catch {
    return { ok: false, error: { kind: "internal" } };
  }
}

function showError(r: Result<unknown>): boolean {
  if (r.ok) {
    $("error").textContent = "";
    return false;
  }
  $("error").textContent = errorText(r.error);
  if (r.error.kind === "token") $("pairing").hidden = false;
  return true;
}

let tabId: number | undefined;
let tabUrl = "";
let slug: string | null = null;

async function renderTab(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  if (!tab.url || !/^https?:\/\//i.test(tab.url)) {
    $("error").textContent = "Open a job application page";
    return;
  }
  tabId = tab.id;
  tabUrl = tab.url;
  const [match, jobs] = await Promise.all([
    send<Match>({ type: "matchTab", url: tab.url, tabId }),
    send<Job[]>({ type: "jobs" }),
  ]);
  if (showError(match) || showError(jobs) || !match.ok || !jobs.ok) return;
  slug = match.value.slug;
  const job = jobs.value.find((j) => j.slug === slug);
  $("current").textContent = job ? `${job.company}, ${job.role}` : slug ?? "none";
  const select = $<HTMLSelectElement>("choose");
  select.replaceChildren(new Option("Change job...", ""));
  for (const j of jobs.value) select.add(new Option(`${j.company}, ${j.role}`, j.slug, false, j.slug === slug));
  $<HTMLButtonElement>("applied").disabled = !slug;
  $("tab").hidden = false;
}

async function init(): Promise<void> {
  const health = await send<{ cvforge: string }>({ type: "status" });
  if (showError(health) || !health.ok) return;
  $("status").textContent = `Connected, cv-forge ${health.value.cvforge}`;
  await renderTab();
}

$("save-token").addEventListener("click", async () => {
  const token = $<HTMLInputElement>("token").value.trim();
  if (!token) return;
  await send({ type: "setToken", token });
  $("pairing").hidden = true;
  $("status").textContent = "";
  await init();
});

$<HTMLSelectElement>("choose").addEventListener("change", async (e) => {
  const chosen = (e.target as HTMLSelectElement).value;
  if (!chosen || tabId === undefined) return;
  if (!showError(await send({ type: "chooseJob", tabId, slug: chosen, url: tabUrl }))) await renderTab();
});

actionButton($<HTMLButtonElement>("applied"), $("status"), async () => {
  if (!slug) return "";
  const r = await send({ type: "markApplied", slug });
  return showError(r) ? "" : `Marked ${slug} as applied`;
});

// Initial token state: show the field when none is stored.
chrome.storage.local.get("token").then((s) => {
  if (!s.token) $("pairing").hidden = false;
}, () => undefined);
init().catch(() => showError({ ok: false, error: { kind: "internal" } }));
