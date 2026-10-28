import { attachFile, checkRadio, highlight, isCombobox, isEmpty, labelText, selectOption, setValue } from "../content/dom";
import type { Kit } from "../shared/kit";
import type { Result } from "../shared/messages";
import { normaliseQuestion } from "../shared/normalise";
import { countryName, type PickOptions, type PickOutcome } from "../content/combobox";
import type { FieldSlot, ListSlot, PageMap, QuestionSlot, SummaryItem, Target } from "./pagemap";

export type { SummaryItem } from "./pagemap";

export interface Summary {
  filled: SummaryItem[];
  guessed: SummaryItem[];
  attached: SummaryItem[];
  suggested: SummaryItem[];
  needsYou: SummaryItem[];
}

export interface FillDeps {
  pdf(which: "cv" | "letter"): Promise<Result<{ name: string; bytes: ArrayBuffer }>>;
  bank(q: string): Promise<{ question: string; answer: string } | null>;
  suggest(slot: QuestionSlot, answer: string): void;
  /** Chooses an option in a searchable dropdown; without it dropdowns are left to the user. */
  pick?(el: HTMLInputElement, value: string, opts?: PickOptions): Promise<PickOutcome>;
}

const plain = (t: string): string => t.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim().replace(/\s+/g, " ");

// normaliseQuestion drops stopwords ("no"), so also compare accent-folded plain text.
function same(a: string, b: string): boolean {
  const na = normaliseQuestion(a);
  if (na !== "" && na === normaliseQuestion(b)) return true;
  return plain(a) !== "" && plain(a) === plain(b);
}

const first = (t: Target): Element => (Array.isArray(t) ? (t[0] as Element) : t);

function isTargetEmpty(t: Target): boolean {
  return Array.isArray(t) ? t.every((r) => !r.checked) : isEmpty(t);
}

/** Texts the control currently shows, for the already-filled comparison. */
function currentTexts(t: Target): string[] {
  if (Array.isArray(t)) {
    const r = t.find((x) => x.checked);
    return r ? [labelText(r), r.value] : [];
  }
  if (t instanceof HTMLSelectElement) {
    const o = t.selectedOptions[0];
    return o ? [o.text, o.value] : [];
  }
  return [t.value];
}

type Outcome = "set" | "same" | "differs" | "nomatch";

/** Write value into an empty target; never touch a non-empty one. */
function place(t: Target, value: string): Outcome {
  if (!isTargetEmpty(t)) return currentTexts(t).some((c) => same(c, value)) ? "same" : "differs";
  if (Array.isArray(t)) return checkRadio(t, value) ? "set" : "nomatch";
  if (t instanceof HTMLSelectElement) return selectOption(t, value) ? "set" : "nomatch";
  setValue(t, value);
  return "set";
}

function nameOf(el: Element): string {
  return (
    labelText(el) ||
    el.getAttribute("name") ||
    el.getAttribute("placeholder") ||
    el.getAttribute("aria-label") ||
    el.localName
  );
}

export async function fill(map: PageMap, kit: Kit, deps: FillDeps): Promise<Summary> {
  const s: Summary = { filled: [], guessed: [], attached: [], suggested: [], needsYou: [] };
  const needs = (label: string, el: Element | null, note: string): void => {
    if (el) highlight(el, note);
    s.needsYou.push({ label, el, note });
  };

  // Never-filled elements first, so they are flagged even if a later step fails.
  for (const el of map.phone) needs(nameOf(el), el, "phone: fill by hand");
  for (const el of map.consent) needs(nameOf(el), el, "consent: tick by hand");
  for (const el of map.unplaced) {
    needs(nameOf(el), el, isCombobox(el) ? "pick from the list by hand" : "not recognised: fill by hand");
  }

  const step = async (label: string, el: Element | null, run: () => void | Promise<void>): Promise<void> => {
    try {
      await run();
    } catch {
      needs(label, el, `could not fill: ${label}`);
    }
  };
  for (const slot of map.fields) {
    await step(slot.key, first(slot.el), () => fillField(slot, kit, deps, s, needs));
  }
  await fillQuestions(map, kit, deps, s, needs, step);
  await step("salary", map.salary?.el ?? null, () => fillSalary(map, kit, s, needs));
  await fillFiles(map, kit, deps, s, needs, step);
  await fillLists(map, kit, s, needs, step);
  return s;
}

type Needs = (label: string, el: Element | null, note: string) => void;
type Step = (label: string, el: Element | null, run: () => void | Promise<void>) => Promise<void>;

const dropdown = (t: Target): HTMLInputElement | null =>
  !Array.isArray(t) && t instanceof HTMLInputElement && isCombobox(t) ? t : null;

/** Picks value in a dropdown; returns place()'s outcomes, or null when there is no picker. */
async function pickIn(el: HTMLInputElement, value: string, deps: FillDeps, opts?: PickOptions): Promise<Outcome | null> {
  if (!deps.pick) return null;
  return deps.pick(el, value, opts);
}

async function fillField(slot: FieldSlot, kit: Kit, deps: FillDeps, s: Summary, needs: Needs): Promise<void> {
  const field = kit.fields.find((f) => f.key === slot.key);
  if (!field || field.value.trim() === "") return;
  const el = first(slot.el);
  const combo = dropdown(slot.el);
  const value = combo && slot.key === "basics.country" ? countryName(field.value) : field.value;
  const outcome = combo ? await pickIn(combo, value, deps, { prefix: slot.key === "basics.city" }) : place(slot.el, value);
  if (outcome === null) needs(field.label, el, "pick from the list by hand");
  else if (outcome === "set") (slot.guessed ? s.guessed : s.filled).push({ label: field.label, el });
  else if (outcome === "same") s.filled.push({ label: field.label, el, note: "already filled" });
  else if (outcome === "differs") needs(field.label, el, `already filled, kit says ${value}`);
  else needs(field.label, el, `no option matches ${value}`);
}

async function fillQuestions(map: PageMap, kit: Kit, deps: FillDeps, s: Summary, needs: Needs, step: Step): Promise<void> {
  for (const slot of map.questions) {
    await step(slot.label, first(slot.el), () => fillQuestion(slot, kit, deps, s, needs));
  }
}

async function fillQuestion(slot: QuestionSlot, kit: Kit, deps: FillDeps, s: Summary, needs: Needs): Promise<void> {
  {
    const el = first(slot.el);
    const key = normaliseQuestion(slot.label);
    const hit = key === "" ? undefined : kit.answers.find((a) => normaliseQuestion(a.question) === key);
    if (hit) {
      if (slot.maxLength !== null && hit.answer.length > slot.maxLength) {
        needs(slot.label, el, "answer longer than limit");
        return;
      }
      const combo = dropdown(slot.el);
      const outcome = combo ? await pickIn(combo, hit.answer, deps) : place(slot.el, hit.answer);
      if (outcome === null) needs(slot.label, el, "pick from the list by hand");
      else if (outcome === "set") s.filled.push({ label: slot.label, el });
      else if (outcome === "same") s.filled.push({ label: slot.label, el, note: "already filled" });
      else if (outcome === "differs") needs(slot.label, el, "already filled, kit answer differs");
      else needs(slot.label, el, "no option matches the answer");
      return;
    }
    if (!isTargetEmpty(slot.el)) {
      s.filled.push({ label: slot.label, el, note: "already filled" });
      return;
    }
    const banked = await deps.bank(slot.label);
    if (banked) {
      deps.suggest(slot, banked.answer);
      s.suggested.push({ label: slot.label, el, note: banked.answer });
    } else {
      needs(slot.label, el, "no saved answer");
    }
  }
}

function fillSalary(map: PageMap, kit: Kit, s: Summary, needs: Needs): void {
  const slot = map.salary;
  if (!slot) return;
  const sal = kit.salary;
  const label = nameOf(slot.el);
  if (!sal?.confirmed || sal.amount === null || sal.currency === null) {
    needs(label, slot.el, "salary unconfirmed");
    return;
  }
  const curOk = slot.currency === null || slot.currency === sal.currency;
  const perOk = slot.period === null || slot.period === sal.period;
  if (!curOk || !perOk) {
    needs(label, slot.el, `salary wants ${slot.currency ?? sal.currency}/${slot.period ?? sal.period}`);
    return;
  }
  const outcome = place(slot.el, String(Math.round(sal.amount)));
  if (outcome === "set") s.filled.push({ label, el: slot.el });
  else if (outcome === "same") s.filled.push({ label, el: slot.el, note: "already filled" });
  else if (outcome === "differs") needs(label, slot.el, "already filled, kit says " + String(Math.round(sal.amount)));
  else needs(label, slot.el, "salary: pick by hand");
}

async function fillFiles(map: PageMap, kit: Kit, deps: FillDeps, s: Summary, needs: Needs, step: Step): Promise<void> {
  const jobs = [
    { which: "cv" as const, el: map.files.cv, link: kit.links.cv_pdf, label: "CV" },
    { which: "letter" as const, el: map.files.letter, link: kit.links.letter_pdf, label: "Cover letter" },
  ];
  for (const { which, el, link, label } of jobs) {
    if (!el) continue;
    await step(label, el, () => attachOne(which, el, link, label, deps, s, needs));
  }
}

async function attachOne(
  which: "cv" | "letter", el: HTMLInputElement, link: string | null, label: string,
  deps: FillDeps, s: Summary, needs: Needs,
): Promise<void> {
  {
    if ((el.files?.length ?? 0) > 0) {
      s.attached.push({ label, el, note: "already attached" });
      return;
    }
    if (link === null) {
      if (which === "cv") needs(label, el, "no CV PDF in kit");
      return;
    }
    const res = await deps.pdf(which);
    if (res.ok && attachFile(el, res.value.name, res.value.bytes)) {
      s.attached.push({ label, el, note: res.value.name });
    } else {
      needs(label, el, `attach manually: ${link}`);
    }
  }
}

async function fillLists(map: PageMap, kit: Kit, s: Summary, needs: Needs, step: Step): Promise<void> {
  for (const list of map.lists) {
    const items: unknown[] = kit[list.kind];
    let canOpen = true;
    for (let i = 0; i < items.length; i++) {
      const name = `${list.kind} ${i + 1}`;
      await step(name, null, async () => {
        let entry: HTMLElement | null | undefined = list.existing()[i];
        if (!entry && canOpen) {
          entry = await open(list);
          if (!entry) canOpen = false;
        }
        if (!entry) {
          needs(name, null, `add ${list.kind} entry by hand`);
          return;
        }
        const res = list.fillEntry(entry, items[i]);
        s.filled.push(...res.filled);
        s.needsYou.push(...res.needsYou);
      });
      // an openEntry that threw must not be retried either
      if (s.needsYou.at(-1)?.note === `could not fill: ${name}`) canOpen = false;
    }
  }
}

function open(list: ListSlot): Promise<HTMLElement | null> {
  return list.add && list.openEntry ? list.openEntry() : Promise.resolve(null);
}
