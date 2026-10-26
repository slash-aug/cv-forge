// The ONLY place in the extension allowed to click anything. It refuses whatever
// can move an application forward; callers pass an adapter allow-list of selectors.
export type AllowList = readonly string[];

// Applied to accent-folded lowercase text: JS \b is ASCII-only, so "próximo" is
// checked as "proximo" and "avançar" as "avancar".
const FORBIDDEN =
  /\b(submit|next|continue|apply|send|finish|review|enviar|proximo|próximo|continuar|candidatar|finalizar|avancar|avançar|concluir)\b/;

function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

function attr(el: Element, name: string): string {
  return (el.getAttribute(name) ?? "").trim().toLowerCase();
}

function movesForward(el: Element): boolean {
  const type = attr(el, "type");
  if (type === "submit" || type === "image") return true;
  if (attr(el, "role") === "link") return true;
  if (el.closest("a[href]")) return true;
  if (el.hasAttribute("formaction")) return true;
  const form = (el as { form?: HTMLFormElement | null }).form ?? el.closest("form");
  const isButton = el instanceof HTMLButtonElement;
  // A <button> tied to a form (inside it, or via the form attribute) without type=button submits.
  if (isButton && (form || el.hasAttribute("form")) && type !== "button") return true;
  if (el.hasAttribute("form") && type !== "button") return true;
  return false;
}

function labels(el: Element): string {
  const text = [el.textContent, (el as HTMLInputElement).value, el.getAttribute("aria-label"), el.getAttribute("title")];
  return fold(text.filter((t): t is string => typeof t === "string").join(" "));
}

export function safeClick(el: Element, allow: AllowList): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (!allow.some((selector) => el.matches(selector))) return false;
  if ((el as { disabled?: boolean }).disabled || el.hasAttribute("disabled")) return false;
  if (attr(el, "aria-disabled") === "true") return false;
  if (movesForward(el)) return false;
  if (FORBIDDEN.test(labels(el))) return false;
  el.click();
  return true;
}
