import { normaliseQuestion } from "../shared/normalise";

type TextField = HTMLInputElement | HTMLTextAreaElement;

function fire(el: Element, ...types: string[]): void {
  for (const type of types) el.dispatchEvent(new Event(type, { bubbles: true }));
}

/** Set a field the way a user would, so React/Vue pick the change up. */
export function setValue(el: TextField, value: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  fire(el, "input", "change");
}

/** Text of the labels tied to a control: label[for], wrapping label, aria-label, aria-labelledby. */
export function labelText(el: Element): string {
  const parts: string[] = [];
  const root = el.getRootNode() as Document | ShadowRoot;
  if (el.id) {
    for (const l of root.querySelectorAll<HTMLLabelElement>("label[for]")) {
      if (l.htmlFor === el.id) parts.push(l.textContent ?? "");
    }
  }
  const wrapping = el.closest("label");
  if (wrapping) parts.push(wrapping.textContent ?? "");
  const aria = el.getAttribute("aria-label");
  if (aria) parts.push(aria);
  for (const id of (el.getAttribute("aria-labelledby") ?? "").split(/\s+/)) {
    if (id) parts.push(root.getElementById?.(id)?.textContent ?? "");
  }
  return parts.join(" ").trim();
}

function plain(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim().replace(/\s+/g, " ");
}

// normaliseQuestion drops stopwords, so answers like "No" (a Portuguese stopword) normalise
// to nothing; fall back to the plain folded text for those.
function same(a: string, b: string): boolean {
  const na = normaliseQuestion(a);
  const nb = normaliseQuestion(b);
  if (na !== "" && na === nb) return true;
  return plain(a) !== "" && plain(a) === plain(b);
}

export function selectOption(el: HTMLSelectElement, value: string): boolean {
  for (const opt of el.options) {
    if (same(opt.value, value) || same(opt.text, value)) {
      el.value = opt.value;
      fire(el, "input", "change");
      return true;
    }
  }
  return false;
}

export function checkRadio(group: HTMLInputElement[], value: string): boolean {
  for (const radio of group) {
    if (same(labelText(radio), value) || same(radio.value, value)) {
      radio.checked = true;
      fire(radio, "input", "change");
      return true;
    }
  }
  return false;
}

export function attachFile(input: HTMLInputElement, name: string, bytes: ArrayBuffer): boolean {
  const transfer = new DataTransfer();
  transfer.items.add(new File([bytes], name, { type: "application/pdf" }));
  input.files = transfer.files;
  fire(input, "input", "change");
  return input.files?.length === 1;
}

export function isEmpty(el: Element): boolean {
  if (el instanceof HTMLSelectElement) return el.selectedIndex <= 0 || el.value === "";
  if (el instanceof HTMLInputElement) {
    if (el.type === "checkbox" || el.type === "radio") return !el.checked;
    if (el.type === "file") return (el.files?.length ?? 0) === 0;
    return el.value.trim() === "";
  }
  if (el instanceof HTMLTextAreaElement) return el.value.trim() === "";
  return (el.textContent ?? "").trim() === "";
}

const previousOutline = new WeakMap<HTMLElement, [string, string]>();

/** Outline plus a reason attribute; outlines take no layout space. */
export function highlight(el: Element, reason: string): void {
  if (el instanceof HTMLElement) {
    if (!previousOutline.has(el)) previousOutline.set(el, [el.style.outline, el.style.outlineOffset]);
    el.style.outline = "2px solid #d97706";
    el.style.outlineOffset = "2px";
  }
  el.setAttribute("data-cvforge-reason", reason);
}

export function clearHighlights(): void {
  for (const el of document.querySelectorAll("[data-cvforge-reason]")) {
    el.removeAttribute("data-cvforge-reason");
    if (el instanceof HTMLElement) {
      const [outline, offset] = previousOutline.get(el) ?? ["", ""];
      el.style.outline = outline;
      el.style.outlineOffset = offset;
      previousOutline.delete(el);
    }
  }
}
