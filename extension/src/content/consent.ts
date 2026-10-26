import { labelText } from "./dom";

const CONSENT =
  /consent|privacy|policy|terms|agree|confirm|gdpr|lgpd|consentimento|privacidade|politica|política|termos|concordo|aceito|declaro|confirmo/i;

/** True for checkboxes that carry consent or a legal confirmation. These are never ticked. */
export function isConsent(el: HTMLInputElement): boolean {
  if (el.type !== "checkbox") return false;
  const text = `${labelText(el)} ${el.name}`;
  const folded = text.normalize("NFKD").replace(/\p{M}/gu, "");
  return CONSENT.test(text) || CONSENT.test(folded);
}
