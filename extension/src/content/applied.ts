import type { Adapter } from "../adapters/types";

const FLAG = "cvforge:submitted";
const THANKS =
  /thank you for (applying|your application)|application (was |has been )?(received|submitted|sent)|candidatura (foi )?(enviada|recebida|realizada)|obrigad[oa] por se candidatar/i;

function flag(): string | null {
  try {
    return sessionStorage.getItem(FLAG);
  } catch {
    return null;
  }
}

/** Remembers that a form on this host was submitted. Only observes: never prevents or triggers anything. */
export function watchSubmit(doc: Document, host: string): void {
  doc.addEventListener(
    "submit",
    () => {
      try {
        sessionStorage.setItem(FLAG, host);
      } catch {
        /* storage blocked: no mark-applied offer */
      }
    },
    true,
  );
}

/** True when the adapter's confirmation page is showing, or a thank-you text follows a submit on this host. */
export function detectSent(doc: Document, loc: URL, adapter: Adapter | null): boolean {
  if (adapter?.confirmation && doc.querySelector(adapter.confirmation)) return true;
  if (flag() !== loc.hostname) return false;
  return THANKS.test(doc.body?.textContent ?? "");
}
