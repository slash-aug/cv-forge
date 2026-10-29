import { labelText } from "./dom";

// The ONLY place in the extension allowed to click anything. It refuses whatever
// can move an application forward; callers pass an adapter allow-list of selectors.
export type AllowList = readonly string[];

// Applied to accent-folded lowercase text: JS \b is ASCII-only, so "próximo" is
// checked as "proximo" and "avançar" as "avancar".
const FORBIDDEN =
  /\b(submit|next|continue|apply|send|finish|review|enviar|proximo|próximo|continuar|candidatar|finalizar|avancar|avançar|concluir|proxima|seguinte|prosseguir|avance|proceed|done|confirm|confirmar)\b/;

function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

function attr(el: Element, name: string): string {
  return (el.getAttribute(name) ?? "").trim().toLowerCase();
}

/** Ancestors of el, crossing shadow boundaries (closest() stops at a shadow root). */
function composedAncestors(el: Element): Element[] {
  const out: Element[] = [];
  let node: Element | null = el;
  while (node) {
    let next: Element | null = node.parentElement;
    if (!next) {
      const root = node.getRootNode();
      next = root instanceof ShadowRoot ? root.host : null;
    }
    if (next) out.push(next);
    node = next;
  }
  return out;
}

function movesForward(el: Element, ancestors: Element[]): boolean {
  const type = attr(el, "type");
  if (type === "submit" || type === "image" || type === "reset") return true;
  if (attr(el, "role") === "link") return true;
  if (ancestors.some((a) => a.matches("a[href], [role=link]"))) return true;
  if (el.hasAttribute("formaction")) return true;
  const form = (el as { form?: HTMLFormElement | null }).form ?? ancestors.find((a) => a.matches("form"));
  const isButton = el instanceof HTMLButtonElement;
  // A <button> tied to a form (inside it, or via the form attribute) without type=button submits.
  if (isButton && (form || el.hasAttribute("form")) && type !== "button") return true;
  if (el.hasAttribute("form") && type !== "button") return true;
  return false;
}

function labels(el: HTMLElement): string {
  const parts: string[] = [labelText(el), (el as HTMLInputElement).value ?? "", el.getAttribute("title") ?? ""];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) parts.push(n.textContent ?? "");
  for (const d of el.querySelectorAll("img[alt], [aria-label], [title]")) {
    parts.push(d.getAttribute("alt") ?? "", d.getAttribute("aria-label") ?? "", d.getAttribute("title") ?? "");
  }
  return fold(parts.join(" "));
}

// Only real buttons are ever clicked; labels, checkboxes, radios and children of
// buttons, links, labels or inputs are refused because clicking them can submit.
const CLICKABLE = "button, input[type=button], div[role=button], span[role=button], li[role=button]";
const CONTAINERS =
  "button, a, label, [role=button], [role=link], input, [role=checkbox], [role=radio], [role=switch], " +
  "[role=option], [role=menuitemcheckbox], summary, details > summary";

/** Shadow root of e, open or closed (closed roots via the extension-only APIs). */
function shadowOf(e: Element): ShadowRoot | null {
  if (e.shadowRoot) return e.shadowRoot;
  try {
    const dom = (globalThis as unknown as { chrome?: { dom?: { openOrClosedShadowRoot?: (x: Element) => unknown } } })
      .chrome?.dom;
    const viaChrome = dom?.openOrClosedShadowRoot?.(e) as ShadowRoot | null | undefined;
    if (viaChrome) return viaChrome;
  } catch {
    // not available in this context
  }
  return (e as { openOrClosedShadowRoot?: ShadowRoot | null }).openOrClosedShadowRoot ?? null;
}

/** True only for an element that sits plainly in the main document's light DOM. */
function inPlainLightDom(el: Element, ancestors: Element[]): boolean {
  if (el.getRootNode() !== el.ownerDocument) return false;
  if (el.assignedSlot !== null) return false;
  return ![el, ...ancestors].some((e) => shadowOf(e) !== null);
}

/**
 * Clicks one option of a searchable dropdown's own list (react-select and the like).
 * Only a plain role=option element inside that listbox, never a button, link, label or
 * input, nothing nested in one, and never an option whose text moves the form forward.
 */
export function clickOption(option: Element, listbox: Element): boolean {
  if (!(option instanceof HTMLElement)) return false;
  if (attr(option, "role") !== "option" || attr(listbox, "role") !== "listbox") return false;
  if (!listbox.contains(option) || option === listbox) return false;
  if (option.matches("button, a, label, input, select, textarea, summary") || option.localName.includes("-")) {
    return false;
  }
  const ancestors = composedAncestors(option);
  if (!inPlainLightDom(option, ancestors)) return false;
  if (ancestors.some((a) => a.matches("button, a, label, [role=button], [role=link], summary"))) return false;
  if (option.querySelector("button, a[href], input, select, textarea, [role=button], [role=link]")) return false;
  if (attr(option, "aria-disabled") === "true" || option.hasAttribute("disabled")) return false;
  if (FORBIDDEN.test(labels(option))) return false;
  option.click();
  return true;
}

export function safeClick(el: Element, allow: AllowList): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (!el.matches(CLICKABLE)) return false;
  if (el.localName.includes("-")) return false;
  const ancestors = composedAncestors(el);
  if (!inPlainLightDom(el, ancestors)) return false;
  if (ancestors.some((a) => a.matches(CONTAINERS))) return false;
  if (!allow.some((selector) => el.matches(selector))) return false;
  if ((el as { disabled?: boolean }).disabled || el.hasAttribute("disabled")) return false;
  if (attr(el, "aria-disabled") === "true") return false;
  if (movesForward(el, ancestors)) return false;
  if (FORBIDDEN.test(labels(el))) return false;
  el.click();
  return true;
}
