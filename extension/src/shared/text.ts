import { normaliseQuestion } from "./normalise";

/** Accent-folded, lowercased text with single spaces. */
export function plain(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim().replace(/\s+/g, " ");
}

/** Same folded text, ignoring accents, case and spacing. */
export function exact(a: string, b: string): boolean {
  return plain(a) !== "" && plain(a) === plain(b);
}

// normaliseQuestion drops stopwords, so answers like "No" (a Portuguese stopword) normalise
// to nothing; fall back to the plain folded text for those.
export function same(a: string, b: string): boolean {
  const na = normaliseQuestion(a);
  if (na !== "" && na === normaliseQuestion(b)) return true;
  return exact(a, b);
}
