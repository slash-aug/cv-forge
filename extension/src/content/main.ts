import { ADAPTERS, adapterFor } from "../adapters/registry";
import type { Adapter } from "../adapters/types";
import { fill, type FillDeps, type Summary } from "../fill/engine";
import type { PageMap, QuestionSlot, Target } from "../fill/pagemap";
import { guessPage, looksLikeApplication } from "../guesser/guess";
import { fromBase64 } from "../shared/bytes";
import { isLinkedInHost } from "../shared/linkedin";
import { errorText, type ApiError, type Match, type Msg, type Result } from "../shared/messages";
import type { Kit } from "../shared/kit";
import { clearSubmitted, detectSent, rememberAdapter, rememberedAdapterName, watchSubmit } from "./applied";
import { checkRadio, isEmpty, selectOption, setValue } from "./dom";
import { inUi, offerSave, showApplied, showButton, showSuggestion, showSummary, type SaveResult } from "./ui";

type Send = (m: Msg) => Promise<Result<any>>;

const RECHECK_MS = 500;
const RECHECK_MAX_MS = 2000;
const INTERNAL: Result<never> = { ok: false, error: { kind: "internal" } };
const first = (t: Target): Element => (Array.isArray(t) ? (t[0] as Element) : t);

let stop: (() => void) | null = null;

/** Controls on the page (outside our UI), as a cheap signature of the current form step. */
function fingerprint(doc: Document): string {
  return [...doc.querySelectorAll("input, textarea, select")]
    .filter((c) => !inUi(c))
    .map((c) => `${c.localName}:${(c as HTMLInputElement).type}:${c.id}:${c.getAttribute("name") ?? ""}`)
    .join("|");
}

function useAnswer(target: Target, answer: string): void {
  const empty = Array.isArray(target) ? target.every((r) => !r.checked) : isEmpty(target);
  if (!empty) return;
  if (Array.isArray(target)) checkRadio(target, answer);
  else if (target instanceof HTMLSelectElement) selectOption(target, answer);
  else setValue(target, answer);
}

function findingMessages(error: ApiError): string[] {
  if (error.kind === "http" && typeof error.body === "object" && error.body !== null) {
    const findings = (error.body as { findings?: unknown }).findings;
    if (Array.isArray(findings)) {
      const msgs = findings
        .map((f) => (f as { message?: unknown } | null)?.message)
        .filter((m): m is string => typeof m === "string");
      if (msgs.length > 0) return msgs;
    }
  }
  return [errorText(error)];
}

/** The form holding the mapped controls, if the page has one. */
function mappedForm(map: PageMap): HTMLFormElement | null {
  const probe = [...map.fields.map((f) => first(f.el)), map.files.cv, map.files.letter];
  for (const c of probe) {
    const form = (c as { form?: HTMLFormElement | null } | undefined)?.form;
    if (form) return form;
  }
  return null;
}

export async function start(win: Window, rawSend: Send): Promise<void> {
  // A reloaded extension rejects or answers nothing; both become the internal error.
  const send: Send = async (m) => {
    try {
      const r = await rawSend(m);
      return r && typeof r === "object" && "ok" in r ? r : INTERNAL;
    } catch {
      return INTERNAL;
    }
  };
  stop?.();
  stop = null;
  const doc = win.document;
  const host = win.location.hostname;
  if (isLinkedInHost(host)) return;

  const loc = (): URL => new URL(win.location.href);
  const adapter = () => adapterFor(loc(), doc);
  const isApplication = (): boolean => adapter() !== null || looksLikeApplication(doc);
  // The confirmation page lacks the form an adapter claims on, so remember who claimed the page.
  let claimed: Adapter | null = ADAPTERS.find((a) => a.name === rememberedAdapterName(host)) ?? null;
  const noteClaim = (): void => {
    const a = adapter();
    if (!a) return;
    claimed = a;
    rememberAdapter(host, a.name);
  };
  noteClaim();
  const sent = (): boolean => detectSent(doc, loc(), adapter() ?? claimed);

  const watchForm = (): void => {
    try {
      const a = adapter();
      const form = mappedForm(a ? a.map(doc) : guessPage(doc));
      if (form) watchSubmit(form, host);
    } catch {
      /* no mapped form: no mark-applied offer */
    }
  };
  if (isApplication()) watchForm();

  let slug: string | null = null;
  let busy = false;
  let appliedOffered = false;
  let known = "";

  const offerApplied = (): void => {
    if (appliedOffered || slug === null || !sent()) return;
    appliedOffered = true;
    clearSubmitted();
    const s = slug;
    showApplied(async () => {
      const r = await send({ type: "markApplied", slug: s });
      if (r.ok) clearSubmitted();
      return r.ok ? { ok: true, text: "Marked as applied" } : { ok: false, text: errorText(r.error) };
    });
  };

  const runFill = async (match: Match): Promise<void> => {
    const current = slug as string;
    const label = buttonLabel(match);
    busy = true;
    try {
      showButton("Filling...", () => {}, true);
      const k = await send({ type: "kit", slug: current });
      if (!k.ok) {
        showButton(errorText(k.error), () => void runFill(match), false);
        return;
      }
      const kit = k.value as Kit;
      const a = adapter();
      const map = a ? a.map(doc) : guessPage(doc);
      const summary = await fill(map, kit, depsFor(current, kit));
      showSummary(summary);
      offerSaves(map, summary, current);
      showButton(label, () => void runFill(match), false);
    } catch {
      showButton(errorText({ kind: "internal" }), () => void runFill(match), false);
    } finally {
      busy = false;
      known = fingerprint(doc);
    }
  };

  const depsFor = (current: string, kit: Kit): FillDeps => ({
    async pdf(which) {
      const r = await send({ type: "pdf", slug: current, which });
      if (!r.ok) return r;
      return { ok: true, value: { name: r.value.name, bytes: fromBase64(r.value.base64) } };
    },
    async bank(q) {
      try {
        const r = await send({ type: "bank", q, lang: kit.lang });
        return r.ok ? r.value : null;
      } catch {
        return null;
      }
    },
    suggest(slot: QuestionSlot, answer: string) {
      showSuggestion(slot, answer, () => useAnswer(slot.el, answer));
    },
  });

  const offerSaves = (map: PageMap, summary: Summary, current: string): void => {
    for (const item of summary.needsYou) {
      if (item.note !== "no saved answer") continue;
      const slot = map.questions.find((q) => first(q.el) === item.el);
      if (!slot) continue;
      offerSave(slot, async (): Promise<SaveResult> => {
        const field = first(slot.el) as HTMLInputElement | HTMLTextAreaElement;
        const r = await send({ type: "saveAnswer", slug: current, question: slot.label, answer: field.value.trim() });
        return r.ok ? { saved: true } : { saved: false, messages: findingMessages(r.error) };
      });
    }
  };

  const buttonLabel = (match: Match): string => {
    const job = match.candidates.find((c) => c.slug === slug);
    return job ? `Fill for ${job.company}, ${job.role}` : `Fill for ${slug}`;
  };

  let seq = 0;
  const init = async (): Promise<void> => {
    const mine = ++seq;
    known = fingerprint(doc);
    noteClaim();
    if (isApplication()) watchForm();
    offerApplied();
    const app = isApplication();
    if (!app && !sent()) return;
    const a = adapter();
    const r = await send({
      type: "matchTab",
      url: win.location.href,
      site: a?.name,
      jobId: a?.jobId(loc(), doc) ?? undefined,
    });
    if (mine !== seq) return; // a newer check superseded this one
    if (!r.ok) {
      // A guesser-only page may not be a job form at all: stay quiet there; the popup still says why.
      const quiet = a === null && (r.error.kind === "down" || r.error.kind === "token");
      if (app && !quiet) showButton(errorText(r.error), () => void init(), false);
      return;
    }
    const match = r.value as Match;
    slug = match.slug;
    if (!app) {
      // thank-you page only: no form to fill, just the mark-applied prompt
    } else if (slug === null) {
      showButton("Choose job in the cv-forge popup", () => void init(), false);
    } else {
      showButton(buttonLabel(match), () => void runFill(match), false);
    }
    offerApplied();
  };

  // Always observed, so a form rendered after document_idle still gets the button.
  // Mutations inside the UI are ignored; highlights only change attributes, which are not observed.
  let timer: ReturnType<typeof setTimeout> | undefined;
  let maxTimer: ReturnType<typeof setTimeout> | undefined;
  const recheck = (): void => {
    clearTimeout(timer);
    clearTimeout(maxTimer);
    maxTimer = undefined;
    if (busy) return;
    offerApplied();
    // Runs on every page, so the cheap fingerprint gates the application check.
    const now = fingerprint(doc);
    if (now === known) return;
    if (isApplication()) void init();
    else known = now;
  };
  const observer = new MutationObserver((records) => {
    if (records.every((r) => inUi(r.target))) return;
    clearTimeout(timer);
    timer = setTimeout(recheck, RECHECK_MS);
    // A page that mutates constantly must still get checked.
    maxTimer ??= setTimeout(recheck, RECHECK_MAX_MS);
  });
  if (doc.body) observer.observe(doc.body, { childList: true, subtree: true });

  // After choosing the job in the popup the tab regains focus: ask again while no job is known.
  const reask = (): void => {
    if (slug === null && !busy && isApplication()) void init();
  };
  win.addEventListener("focus", reask);
  doc.addEventListener("visibilitychange", reask);
  stop = () => {
    observer.disconnect();
    clearTimeout(timer);
    clearTimeout(maxTimer);
    win.removeEventListener("focus", reask);
    doc.removeEventListener("visibilitychange", reask);
  };

  await init();
}

if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage && typeof document !== "undefined") {
  void start(window, (m) => chrome.runtime.sendMessage(m));
}
