import type { Summary } from "../fill/engine";
import type { QuestionSlot, SummaryItem, Target } from "../fill/pagemap";

// Everything lives in one closed shadow root so page CSS cannot leak in or out.
// Text is always set with textContent; page-derived strings are never parsed as HTML.

export type SaveResult = { saved: true } | { saved: false; messages: string[] };

interface Ui {
  host: HTMLElement;
  bar: HTMLElement;
  summary: HTMLElement;
  applied: HTMLElement;
  chips: HTMLElement;
}

const CSS = `
:host{all:initial}
*{box-sizing:border-box;font:13px/1.4 system-ui,sans-serif}
.dock{position:fixed;right:16px;bottom:16px;z-index:2147483647;display:flex;flex-direction:column-reverse;gap:8px;align-items:flex-end;max-width:min(360px,calc(100vw - 32px))}
button{cursor:pointer;border:1px solid #1f2937;background:#111827;color:#fff;border-radius:6px;padding:8px 12px}
button:disabled{opacity:.6;cursor:default}
.panel{background:#fff;color:#111827;border:1px solid #9ca3af;border-radius:8px;padding:10px;max-height:60vh;overflow:auto;width:100%}
.panel h3{margin:8px 0 4px;font-weight:600}
.panel .item{display:block;width:100%;text-align:left;background:#f3f4f6;color:#111827;border:0;margin:2px 0;padding:4px 6px}
.panel .note{color:#4b5563}
.chips{position:absolute;top:0;left:0;z-index:2147483647}
.chip{position:absolute;white-space:nowrap;background:#fff;color:#111827;border:1px solid #9ca3af;border-radius:6px;padding:4px;display:flex;gap:6px;align-items:center}
.chip button{padding:3px 8px}
`;

let ui: Ui | null = null;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function ensure(): Ui {
  if (ui?.host.isConnected) return ui;
  const host = document.createElement("div");
  host.setAttribute("data-cvforge-ui", "");
  const root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = CSS;
  const dock = el("div", undefined, "dock");
  const parts = { bar: el("div"), summary: el("div"), applied: el("div"), chips: el("div", undefined, "chips") };
  dock.append(parts.bar, parts.summary, parts.applied);
  root.append(style, dock, parts.chips);
  document.documentElement.append(host);
  ui = { host, ...parts };
  return ui;
}

/** True for a node inside the UI host (mutation observers use it to ignore the UI's own changes). */
export function inUi(node: Node): boolean {
  const host = ui?.host;
  return host !== undefined && (node === host || host.contains(node));
}

export function showButton(label: string, onClick: () => void, disabled: boolean): void {
  const b = el("button", label);
  b.disabled = disabled;
  b.addEventListener("click", () => onClick());
  ensure().bar.replaceChildren(b);
}

function focusItem(item: SummaryItem): void {
  const target = item.el;
  if (!target) return;
  target.scrollIntoView({ block: "center" });
  if (target instanceof HTMLElement) target.focus();
}

const GROUPS: [keyof Summary, string][] = [
  ["filled", "Filled"],
  ["guessed", "Guessed (check these)"],
  ["attached", "Attached"],
  ["suggested", "Suggested"],
  ["needsYou", "Needs you"],
];

export function showSummary(summary: Summary): void {
  const panel = el("div", undefined, "panel");
  for (const [key, title] of GROUPS) {
    const items = summary[key];
    panel.append(el("h3", `${title} (${items.length})`));
    for (const item of items) {
      const row = el("button", item.label, "item");
      if (item.note) row.append(" ", el("span", item.note, "note"));
      if (item.el) row.addEventListener("click", () => focusItem(item));
      else row.disabled = true;
      panel.append(row);
    }
  }
  const close = el("button", "Close");
  close.addEventListener("click", () => panel.remove());
  panel.append(close);
  ensure().summary.replaceChildren(panel);
}

const chipFor = new Map<Element, HTMLElement>();

function placeChip(field: Element, chip: HTMLElement): void {
  const r = field.getBoundingClientRect();
  chip.style.top = `${r.bottom + window.scrollY + 2}px`;
  chip.style.left = `${r.left + window.scrollX}px`;
  chipFor.get(field)?.remove();
  chipFor.set(field, chip);
  ensure().chips.append(chip);
}

const first = (t: Target): Element => (Array.isArray(t) ? (t[0] as Element) : t);

/** A "Use saved answer" chip next to the field; onUse runs only on click. */
export function showSuggestion(slot: QuestionSlot, answer: string, onUse: () => void): void {
  const chip = el("div", undefined, "chip");
  const use = el("button", "Use saved answer");
  use.title = answer;
  use.addEventListener("click", () => {
    onUse();
    chip.remove();
  });
  chip.append(use);
  placeChip(first(slot.el), chip);
}

const watched = new WeakSet<Element>();

/** On blur of a highlighted text question that now has text, offers to save the answer. */
export function offerSave(slot: QuestionSlot, onSave: () => Promise<SaveResult>): void {
  const field = first(slot.el);
  if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) || watched.has(field)) return;
  watched.add(field);
  field.addEventListener("blur", () => {
    if (!field.hasAttribute("data-cvforge-reason") || field.value.trim() === "") return;
    const chip = el("div", undefined, "chip");
    const save = el("button", "Save answer");
    save.addEventListener("click", async () => {
      save.disabled = true;
      const res = await onSave();
      if (res.saved) {
        chip.replaceChildren(el("span", "Saved"));
        return;
      }
      chip.replaceChildren(...res.messages.map((m) => el("div", m)));
    });
    chip.append(save);
    placeChip(field, chip);
  });
}

/** Prompt shown once the form was sent; onMark runs only on click and returns the text to show. */
export function showApplied(onMark: () => Promise<string>): void {
  const panel = el("div", undefined, "panel");
  panel.append(el("div", "Looks like your application was sent."));
  const mark = el("button", "Mark as applied");
  mark.addEventListener("click", async () => {
    mark.disabled = true;
    panel.replaceChildren(el("div", await onMark()));
  });
  panel.append(mark);
  ensure().applied.replaceChildren(panel);
}
