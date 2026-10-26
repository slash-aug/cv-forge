import { greenhouse } from "./greenhouse";
import type { Adapter } from "./types";

export const ADAPTERS: readonly Adapter[] = [greenhouse];

/** The first adapter that claims the page, or null so the guesser takes over. */
export function adapterFor(loc: URL, doc: Document): Adapter | null {
  return ADAPTERS.find((a) => a.claims(loc, doc)) ?? null;
}
