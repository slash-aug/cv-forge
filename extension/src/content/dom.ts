import { exact, same } from "../shared/text";

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
  // A label and an aria-label often repeat each other ("Phone*" and "Phone"): say it once.
  const key = (t: string): string => t.replace(/[\s*:]+/g, " ").trim().toLowerCase();
  const seen = new Set<string>();
  const unique = parts.map((p) => p.trim()).filter((p) => {
    const k = key(p);
    if (k === "" || seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return unique.join(" ").trim();
}

/**
 * A text input that opens a list to choose from (react-select and the like). Typing into one
 * does not choose an option, so both mappers leave it to the user.
 */
export function isCombobox(el: Element): boolean {
  if (!(el instanceof HTMLInputElement)) return false;
  const auto = el.getAttribute("aria-autocomplete");
  return el.getAttribute("role") === "combobox" || auto === "list" || auto === "both" ||
    el.getAttribute("aria-haspopup") === "listbox";
}

/** First candidate whose texts match: exact folded pass over all, then the normalised pass. */
function pick<T>(items: T[], texts: (item: T) => string[], value: string): T | undefined {
  return (
    items.find((i) => texts(i).some((t) => exact(t, value))) ??
    items.find((i) => texts(i).some((t) => same(t, value)))
  );
}

export function selectOption(el: HTMLSelectElement, value: string): boolean {
  const opt = pick([...el.options], (o) => [o.value, o.text], value);
  if (!opt) return false;
  el.value = opt.value;
  fire(el, "input", "change");
  return true;
}

export function checkRadio(group: HTMLInputElement[], value: string): boolean {
  const radio = pick(group, (r) => [labelText(r), r.value], value);
  if (!radio) return false;
  // Native setter, so frameworks that shadow `checked` still see the change.
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked")?.set?.call(radio, true);
  fire(radio, "input", "change");
  return true;
}

export function attachFile(input: HTMLInputElement, name: string, bytes: ArrayBuffer): boolean {
  const transfer = new DataTransfer();
  transfer.items.add(new File([bytes], name, { type: "application/pdf" }));
  input.files = transfer.files;
  fire(input, "input", "change");
  return input.files?.length === 1;
}

export function isEmpty(el: Element): boolean {
  if (el instanceof HTMLSelectElement) {
    const sel = el.selectedOptions[0];
    return !sel || sel.value === "" || sel.disabled || Boolean(sel.hidden);
  }
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
/** Text of the legend of the fieldset holding el, or "". */
export function legendText(el: Element): string {
  return el.closest("fieldset")?.querySelector("legend")?.textContent ?? "";
}

/** True when the form marks the control as required: required, aria-required or a star in its label. */
export function isRequired(el: Element): boolean {
  if ((el as { required?: boolean }).required) return true;
  if (el.getAttribute("aria-required") === "true") return true;
  return /\*/.test(`${labelText(el)} ${legendText(el)}`);
}

/** Marks el with the reason; `outline` false keeps the marker (save offers use it) without the outline. */
export function highlight(el: Element, reason: string, outline = true): void {
  if (outline && el instanceof HTMLElement) {
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
