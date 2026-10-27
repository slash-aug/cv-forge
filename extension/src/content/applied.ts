import type { Adapter } from "../adapters/types";

const FLAG = "cvforge:submitted";
const ADAPTER = "cvforge:adapter";
const THANKS =
  /thank you for (applying|your application)|application (was |has been )?(received|submitted|sent)|candidatura (foi )?(enviada|recebida|realizada)|obrigad[oa] por se candidatar/i;

function flag(): string | null {
  try {
    return sessionStorage.getItem(FLAG);
  } catch {
    return null;
  }
}

const watchedForms = new WeakSet<HTMLFormElement>();

/** Remembers that the mapped form was submitted. Only observes: never prevents or triggers anything. */
export function watchSubmit(form: HTMLFormElement, host: string): void {
  if (watchedForms.has(form)) return;
  watchedForms.add(form);
  form.addEventListener("submit", () => {
    try {
      sessionStorage.setItem(FLAG, host);
    } catch {
      /* storage blocked: no mark-applied offer */
    }
  });
}

/** Forgets the submit mark, so a reload of the thank-you page does not offer again. */
export function clearSubmitted(): void {
  try {
    sessionStorage.removeItem(FLAG);
  } catch {
    /* nothing to clear */
  }
}

/** The confirmation page no longer has the form the adapter claims on, so its name is kept per host. */
export function rememberAdapter(host: string, name: string): void {
  try {
    sessionStorage.setItem(ADAPTER, `${host}=${name}`);
  } catch {
    /* storage blocked: the in-memory copy still works */
  }
}

export function rememberedAdapterName(host: string): string | null {
  try {
    const v = sessionStorage.getItem(ADAPTER) ?? "";
    return v.startsWith(`${host}=`) ? v.slice(host.length + 1) : null;
  } catch {
    return null;
  }
}

/** True when the adapter's confirmation page is showing, or a thank-you text follows a submit on this host. */
export function detectSent(doc: Document, loc: URL, adapter: Adapter | null): boolean {
  if (adapter?.confirmation && doc.querySelector(adapter.confirmation)) return true;
  if (flag() !== loc.hostname) return false;
  return THANKS.test(doc.body?.textContent ?? "");
}
