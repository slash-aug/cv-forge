import { attachFile, checkRadio, highlight, isEmpty, labelText, selectOption, setValue } from "../content/dom";
import type { Kit } from "../shared/kit";
import type { Result } from "../shared/messages";
import { normaliseQuestion } from "../shared/normalise";
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

  for (const slot of map.fields) fillField(slot, kit, s, needs);
  await fillQuestions(map, kit, deps, s, needs);
  fillSalary(map, kit, s, needs);
  await fillFiles(map, kit, deps, s, needs);
  await fillLists(map, kit, s, needs);

  for (const el of map.phone) needs(nameOf(el), el, "phone: fill by hand");
  for (const el of map.consent) needs(nameOf(el), el, "consent: tick by hand");
  for (const el of map.unplaced) needs(nameOf(el), el, "not recognised: fill by hand");
  return s;
}

type Needs = (label: string, el: Element | null, note: string) => void;

function fillField(slot: FieldSlot, kit: Kit, s: Summary, needs: Needs): void {
  const field = kit.fields.find((f) => f.key === slot.key);
  if (!field || field.value.trim() === "") return;
  const el = first(slot.el);
  const outcome = place(slot.el, field.value);
  if (outcome === "set") (slot.guessed ? s.guessed : s.filled).push({ label: field.label, el });
  else if (outcome === "same") s.filled.push({ label: field.label, el, note: "already filled" });
  else if (outcome === "differs") needs(field.label, el, `already filled, kit says ${field.value}`);
  else needs(field.label, el, `no option matches ${field.value}`);
}

async function fillQuestions(map: PageMap, kit: Kit, deps: FillDeps, s: Summary, needs: Needs): Promise<void> {
  for (const slot of map.questions) {
    const el = first(slot.el);
    const key = normaliseQuestion(slot.label);
    const hit = key === "" ? undefined : kit.answers.find((a) => normaliseQuestion(a.question) === key);
    if (hit) {
      if (slot.maxLength !== null && hit.answer.length > slot.maxLength) {
        needs(slot.label, el, "answer longer than limit");
        continue;
      }
      const outcome = place(slot.el, hit.answer);
      if (outcome === "set") s.filled.push({ label: slot.label, el });
      else if (outcome === "same") s.filled.push({ label: slot.label, el, note: "already filled" });
      else if (outcome === "differs") needs(slot.label, el, "already filled, kit answer differs");
      else needs(slot.label, el, "no option matches the answer");
      continue;
    }
    if (!isTargetEmpty(slot.el)) continue;
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
  else needs(label, slot.el, "already filled, kit says " + String(Math.round(sal.amount)));
}

async function fillFiles(map: PageMap, kit: Kit, deps: FillDeps, s: Summary, needs: Needs): Promise<void> {
  const jobs = [
    { which: "cv" as const, el: map.files.cv, link: kit.links.cv_pdf, label: "CV" },
    { which: "letter" as const, el: map.files.letter, link: kit.links.letter_pdf, label: "Cover letter" },
  ];
  for (const { which, el, link, label } of jobs) {
    if (!el) continue;
    if ((el.files?.length ?? 0) > 0) {
      s.attached.push({ label, el, note: "already attached" });
      continue;
    }
    if (link === null) {
      if (which === "cv") needs(label, el, "no CV PDF in kit");
      continue;
    }
    const res = await deps.pdf(which);
    if (res.ok && attachFile(el, res.value.name, res.value.bytes)) {
      s.attached.push({ label, el, note: res.value.name });
    } else {
      needs(label, el, `attach manually: ${link}`);
    }
  }
}

async function fillLists(map: PageMap, kit: Kit, s: Summary, needs: Needs): Promise<void> {
  for (const list of map.lists) {
    const items: unknown[] = kit[list.kind];
    for (let i = 0; i < items.length; i++) {
      const entry = list.existing()[i] ?? (await open(list));
      if (!entry) {
        needs(`${list.kind} ${i + 1}`, null, `add ${list.kind} entry by hand`);
        continue;
      }
      s.filled.push(...list.fillEntry(entry, items[i]));
    }
  }
}

function open(list: ListSlot): Promise<HTMLElement | null> {
  return list.add && list.openEntry ? list.openEntry() : Promise.resolve(null);
}
