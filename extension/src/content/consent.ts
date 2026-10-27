import { labelText } from "./dom";

const CONSENT =
  /consent|privacy|policy|terms|agree|confirm|gdpr|lgpd|consentimento|privacidade|politica|política|termos|concordo|aceito|declaro|confirmo/i;

/** True when the text reads as consent or a legal confirmation, with or without accents. */
export function isConsentText(text: string): boolean {
  return CONSENT.test(text) || CONSENT.test(text.normalize("NFKD").replace(/\p{M}/gu, ""));
}

/** True for checkboxes that carry consent or a legal confirmation. These are never ticked. */
export function isConsent(el: HTMLInputElement): boolean {
  if (el.type !== "checkbox") return false;
  return isConsentText(`${labelText(el)} ${el.name}`);
}
