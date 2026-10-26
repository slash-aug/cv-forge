export type Variants = Record<"200" | "500" | "1000" | "2000", string>;

const ORDER = ["2000", "1000", "500", "200"] as const;

/** Longest non-empty variant within maxLength ("2000" when unlimited), or "" when none fits. */
export function pickDescription(desc: Variants, maxLength: number | null): string {
  if (maxLength === null) return desc["2000"];
  for (const key of ORDER) {
    const text = desc[key];
    if (text !== "" && text.length <= maxLength) return text;
  }
  return "";
}
