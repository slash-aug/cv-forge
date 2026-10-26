import { adapterFor } from "../adapters/registry";
import { fill, type FillDeps, type Summary } from "../fill/engine";
import type { PageMap, QuestionSlot, Target } from "../fill/pagemap";
import { guessPage, looksLikeApplication } from "../guesser/guess";
import { fromBase64 } from "../shared/bytes";
import { isLinkedInHost } from "../shared/linkedin";
import { errorText, type ApiError, type Match, type Msg, type Result } from "../shared/messages";
import type { Kit } from "../shared/kit";
import { detectSent, watchSubmit } from "./applied";
import { checkRadio, selectOption, setValue } from "./dom";
import { inUi, offerSave, showApplied, showButton, showSuggestion, showSummary, type SaveResult } from "./ui";

type Send = (m: Msg) => Promise<Result<any>>;

const RECHECK_MS = 500;
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

export async function start(win: Window, send: Send): Promise<void> {
  stop?.();
  stop = null;
  const doc = win.document;
  const host = win.location.hostname;
  if (isLinkedInHost(host)) return;

  const loc = (): URL => new URL(win.location.href);
  const adapter = () => adapterFor(loc(), doc);
  const isApplication = (): boolean => adapter() !== null || looksLikeApplication(doc);
  const sent = (): boolean => detectSent(doc, loc(), adapter());

  // A thank-you page loaded after a submit is not a form, but may still offer "Mark as applied".
  if (!isApplication() && !sent()) return;
  if (isApplication()) watchSubmit(doc, host);

  let slug: string | null = null;
  let busy = false;
  let appliedOffered = false;
  let known = "";

  const offerApplied = (): void => {
    if (appliedOffered || slug === null || !sent()) return;
    appliedOffered = true;
    const s = slug;
    showApplied(async () => {
      const r = await send({ type: "markApplied", slug: s });
      return r.ok ? "Marked as applied" : errorText(r.error);
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

  const init = async (): Promise<void> => {
    known = fingerprint(doc);
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
    if (!r.ok) {
      if (app) showButton(errorText(r.error), () => void init(), false);
      return;
    }
    const match = r.value as Match;
    slug = match.slug;
    if (!app) {
      // thank-you page only: no form to fill, just the mark-applied prompt
    } else if (slug === null) {
      showButton("Choose job in the cv-forge popup", () => {}, true);
    } else {
      showButton(buttonLabel(match), () => void runFill(match), false);
    }
    offerApplied();
  };

  // Mutations inside the UI are ignored; highlights only change attributes, which are not observed.
  let timer: ReturnType<typeof setTimeout> | undefined;
  const recheck = (): void => {
    if (busy) return;
    offerApplied();
    if (isApplication() && fingerprint(doc) !== known) void init();
  };
  const observer = new MutationObserver((records) => {
    if (records.every((r) => inUi(r.target))) return;
    clearTimeout(timer);
    timer = setTimeout(recheck, RECHECK_MS);
  });
  if (doc.body) observer.observe(doc.body, { childList: true, subtree: true });
  stop = () => {
    observer.disconnect();
    clearTimeout(timer);
  };

  await init();
}

if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage && typeof document !== "undefined") {
  void start(window, (m) => chrome.runtime.sendMessage(m));
}
