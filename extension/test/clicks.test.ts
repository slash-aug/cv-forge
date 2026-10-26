import { beforeEach, describe, expect, test, vi } from "vitest";
import { safeClick } from "../src/content/clicks";

const ALLOW = ["button", "input", "a", "div", "span"];

function make(html: string): HTMLElement {
  document.body.innerHTML = html;
  const el = document.body.querySelector<HTMLElement>("[data-t]")!;
  el.click = vi.fn();
  return el;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("safeClick", () => {
  test.each(["Submit", "Next", "Continuar", "Enviar candidatura", "Apply now", "Próximo",
    "Avançar", "Send", "Finish", "Review", "Candidatar", "Finalizar", "Concluir"])(
    "refuses %s even when allow-listed",
    (label) => {
      const el = make(`<button type="button" data-t>${label}</button>`);
      expect(safeClick(el, ALLOW)).toBe(false);
      expect(el.click).not.toHaveBeenCalled();
    },
  );

  test("refuses forbidden words in value, aria-label and title", () => {
    for (const attrs of ['value="Next"', 'aria-label="Continue"', 'title="Enviar"']) {
      const el = make(`<input type="button" ${attrs} data-t>`);
      expect(safeClick(el, ALLOW)).toBe(false);
      expect(el.click).not.toHaveBeenCalled();
    }
  });

  test("refuses forbidden words with decomposed accents", () => {
    const el = make(`<button type="button" data-t>Próximo</button>`);
    expect(safeClick(el, ALLOW)).toBe(false);
  });

  test("a forbidden word inside another word is not a match", () => {
    const el = make(`<button type="button" data-t>Add nextdoor neighbour</button>`);
    expect(safeClick(el, ALLOW)).toBe(true);
  });

  test("refuses type=submit and default form button", () => {
    let el = make(`<form><button type="submit" data-t>Add experience</button></form>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    el = make(`<form><button data-t>Add experience</button></form>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    el = make(`<form><input type="submit" value="Add experience" data-t></form>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("clicks a type=button inside a form", () => {
    const el = make(`<form><button type="button" data-t>Add experience</button></form>`);
    expect(safeClick(el, ALLOW)).toBe(true);
    expect(el.click).toHaveBeenCalledTimes(1);
  });

  test("refuses role=link", () => {
    const el = make(`<div role="link" data-t>Add experience</div>`);
    expect(safeClick(el, ALLOW)).toBe(false);
  });

  test("refuses element not in allow list", () => {
    const el = make(`<button type="button" data-t>Add experience</button>`);
    expect(safeClick(el, [".other"])).toBe(false);
    expect(safeClick(el, [])).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test.each(["Add experience", "Adicionar experiência"])("clicks allow-listed %s", (label) => {
    const el = make(`<button type="button" data-t>${label}</button>`);
    expect(safeClick(el, ["button"])).toBe(true);
    expect(el.click).toHaveBeenCalledTimes(1);
  });

  test("refuses an anchor with an href, or inside one", () => {
    let el = make(`<a href="/next-page" data-t>Add experience</a>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    el = make(`<a href="/x"><span data-t>Add experience</span></a>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("refuses input type=image", () => {
    const el = make(`<input type="image" alt="Add experience" data-t>`);
    expect(safeClick(el, ALLOW)).toBe(false);
  });

  test("refuses disabled and aria-disabled", () => {
    let el = make(`<button type="button" disabled data-t>Add experience</button>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    el = make(`<div aria-disabled="true" data-t>Add experience</div>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("refuses formaction and an external form attribute", () => {
    let el = make(`<button type="button" formaction="/apply" data-t>Add experience</button>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    el = make(`<form id="f"></form><button form="f" data-t>Add experience</button>`);
    expect(safeClick(el, ALLOW)).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });
});
