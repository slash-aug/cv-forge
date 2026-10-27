import { describe, expect, test } from "vitest";
import { isConsent, isConsentText } from "../src/content/consent";

function box(html: string): HTMLInputElement {
  document.body.innerHTML = html;
  return document.querySelector<HTMLInputElement>("input")!;
}

describe("isConsent", () => {
  test.each(["I agree to the privacy policy", "Li e concordo com os termos", "I confirm the information is true"])(
    "wrapping label: %s",
    (text) => {
      expect(isConsent(box(`<label><input type="checkbox"> ${text}</label>`))).toBe(true);
    },
  );

  test("label for", () => {
    expect(isConsent(box('<input type="checkbox" id="c"><label for="c">Aceito a política</label>'))).toBe(true);
  });

  test("aria-label", () => {
    expect(isConsent(box('<input type="checkbox" aria-label="GDPR consent">'))).toBe(true);
  });

  test("aria-labelledby", () => {
    expect(
      isConsent(box('<span id="l">Declaro que li</span><input type="checkbox" aria-labelledby="l">')),
    ).toBe(true);
  });

  test("name attribute", () => {
    expect(isConsent(box('<input type="checkbox" name="lgpd_ok">'))).toBe(true);
  });

  test("false for 'Open to relocation'", () => {
    expect(isConsent(box('<label><input type="checkbox" name="reloc"> Open to relocation</label>'))).toBe(false);
  });

  test("false for a non-checkbox", () => {
    expect(isConsent(box('<label><input type="text"> I agree</label>'))).toBe(false);
  });
});

describe("isConsentText", () => {
  test("matches consent phrases, accent-folded, and rejects ordinary text", () => {
    expect(isConsentText("Declaro que li a política de privacidade")).toBe(true);
    expect(isConsentText("I accept the privacy notice")).toBe(true);
    expect(isConsentText("Which team are you applying to?")).toBe(false);
  });
});
