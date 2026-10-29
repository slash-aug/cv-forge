import { exact, plain, same } from "../shared/text";
import { clickOption } from "./clicks";
import { setValue } from "./dom";

export type PickOutcome = "set" | "same" | "differs" | "nomatch";

export interface PickOptions {
  /** Also accept an option that starts with the value and a comma ("Londrina, Paraná, Brazil"). */
  prefix?: boolean;
  /** How long to wait for the list to show options, per search. */
  waitMs?: number;
}

const POLL_MS = 50;
const WAIT_MS = 3000;
/** An open list that stays without options this long has nothing to offer. */
const SETTLE_MS = 300;

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/** "Yes. I will need a permit." starts with the option "Yes"; plain "Yesterday" does not. */
function leads(option: string, value: string): boolean {
  const o = plain(option);
  const v = plain(value);
  return o !== "" && v.length > o.length && v.startsWith(o) && /[.,;:!?]/.test(v.charAt(o.length));
}

function matchLevel(text: string, value: string, opts: PickOptions): number {
  if (exact(text, value)) return 1;
  if (same(text, value)) return 2;
  if (leads(text, value)) return 3;
  if (opts.prefix && plain(text).startsWith(`${plain(value)},`)) return 4;
  return 0;
}

/** The text a react-select style dropdown shows as its chosen value, if any. */
function shownValue(input: HTMLInputElement): string | null {
  const control = input.closest('[class*="control"]');
  const text = control?.querySelector('[class*="single-value"]')?.textContent?.trim();
  return text ? text : null;
}

function listboxOf(input: HTMLInputElement): Element | null {
  for (const id of `${input.getAttribute("aria-controls") ?? ""} ${input.getAttribute("aria-owns") ?? ""}`.split(/\s+/)) {
    const el = id ? input.ownerDocument.getElementById(id) : null;
    if (el?.getAttribute("role") === "listbox") return el;
  }
  // Nearest listbox in the dropdown's own container (a few levels up, never the whole form).
  let node: Element | null = input.parentElement;
  for (let i = 0; node && i < 6; i++, node = node.parentElement) {
    const list = node.querySelector("[role=listbox]");
    if (list) return list;
  }
  return null;
}

/** The listbox once it has options; `opened` says whether any list showed up at all. */
async function waitForOptions(input: HTMLInputElement, waitMs: number): Promise<{ list: Element | null; opened: boolean }> {
  let emptySince: number | null = null;
  for (let waited = 0; ; waited += POLL_MS) {
    const list = listboxOf(input);
    if (list?.querySelector("[role=option]")) return { list, opened: true };
    if (list) emptySince ??= waited;
    if (emptySince !== null && waited - emptySince >= SETTLE_MS) return { list: null, opened: true };
    if (waited >= waitMs) return { list: null, opened: emptySince !== null };
    await sleep(POLL_MS);
  }
}

/** The text before the first punctuation mark, searched when the whole answer finds nothing. */
function leadingPart(value: string): string | null {
  const m = /^([^.,;:!?]+)[.,;:!?]/.exec(value.trim());
  return m?.[1]?.trim() || null;
}

/**
 * Chooses `value` in a searchable dropdown: types it to filter the list, then clicks the best
 * matching option through clickOption. A dropdown that already shows a value is never changed.
 */
export async function pickOption(input: HTMLInputElement, value: string, opts: PickOptions = {}): Promise<PickOutcome> {
  const want = value.trim();
  if (want === "") return "nomatch";
  const current = shownValue(input);
  if (current !== null) return matchLevel(current, want, opts) > 0 ? "same" : "differs";

  const terms = [...new Set([want, leadingPart(want)].filter((t): t is string => !!t))];
  for (const term of terms) {
    input.focus();
    setValue(input, term);
    const { list, opened } = await waitForOptions(input, opts.waitMs ?? WAIT_MS);
    if (!opened) break; // no list at all: another search would not open one either
    if (!list) continue;
    const ranked = [...list.querySelectorAll("[role=option]")]
      .map((o) => ({ o, level: matchLevel(o.textContent ?? "", want, opts) }))
      .filter((x) => x.level > 0)
      .sort((a, b) => a.level - b.level);
    if (ranked.find(({ o }) => clickOption(o, list))) {
      await sleep(0);
      const now = shownValue(input);
      if (now !== null && matchLevel(now, want, opts) > 0) return "set";
      break;
    }
  }
  if (shownValue(input) === null) setValue(input, "");
  input.blur();
  return "nomatch";
}

/** "BR" becomes "Brazil"; names and unknown values pass through. */
export function countryName(value: string): string {
  const v = value.trim();
  if (!/^[A-Za-z]{2}$/.test(v)) return v;
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(v.toUpperCase()) ?? v;
  } catch {
    return v;
  }
}
