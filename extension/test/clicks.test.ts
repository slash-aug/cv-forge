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

  test("refuses a child of a submit button, with a spying form", () => {
    document.body.innerHTML = `<form id="f"><button type="submit"><span data-t>Add experience</span></button></form>`;
    const el = document.querySelector<HTMLElement>("[data-t]")!;
    const submit = vi.fn((e: Event) => e.preventDefault());
    document.getElementById("f")!.addEventListener("submit", submit);
    expect(safeClick(el, ["span"])).toBe(false);
    expect(submit).not.toHaveBeenCalled();
  });

  test("refuses a span inside a typeless button in a form", () => {
    const el = make(`<form><button><span data-t>Add experience</span></button></form>`);
    expect(safeClick(el, ["span"])).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("refuses a label whose control is a submitter", () => {
    const el = make(`<form><button type="submit" id="s">x</button></form><label for="s" data-t>Add experience</label>`);
    expect(safeClick(el, ["label"])).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("refuses checkboxes and radios outright, consent stays unticked", () => {
    const el = make(`<label><input type="checkbox" data-t> Add experience</label>`);
    expect(safeClick(el, ["input"])).toBe(false);
    expect((el as HTMLInputElement).checked).toBe(false);
    const r = make(`<input type="radio" data-t>`);
    expect(safeClick(r, ["input"])).toBe(false);
  });

  test("clicks an input type=button and a role=button element", () => {
    expect(safeClick(make(`<input type="button" value="Add experience" data-t>`), ["input"])).toBe(true);
    expect(safeClick(make(`<div role="button" data-t>Add experience</div>`), ["div"])).toBe(true);
  });

  test("reads text from aria-labelledby", () => {
    const el = make(`<span id="l">Next</span><button type="button" aria-labelledby="l" data-t>+</button>`);
    expect(safeClick(el, ["button"])).toBe(false);
  });

  test("reads descendant img alt, aria-label and title", () => {
    for (const inner of ['<img alt="Next">', '<i aria-label="Continue"></i>', '<i title="Enviar"></i>']) {
      const el = make(`<button type="button" data-t>${inner}</button>`);
      expect(safeClick(el, ["button"])).toBe(false);
    }
  });

  test("joins adjacent text nodes with spaces", () => {
    const el = make(`<button type="button" data-t><span>Add</span><span>Submit</span><span>application</span></button>`);
    expect(safeClick(el, ["button"])).toBe(false);
  });

  test.each(["Próxima etapa", "Prosseguir", "Seguinte", "Proceed", "Done", "Confirm", "Confirmar", "Avance"])(
    "refuses %s",
    (label) => {
      const el = make(`<button type="button" data-t>${label}</button>`);
      expect(safeClick(el, ["button"])).toBe(false);
    },
  );

  test("role=button does not make a non-button clickable", () => {
    let el = make(`<form><button type="submit" id="s">x</button></form><label role="button" for="s" data-t>Add experience</label>`);
    expect(safeClick(el, ["label"])).toBe(false);
    el = make(`<input type="checkbox" role="button" data-t>`);
    expect(safeClick(el, ["input"])).toBe(false);
    expect((el as HTMLInputElement).checked).toBe(false);
    el = make(`<input type="radio" role="button" data-t>`);
    expect(safeClick(el, ["input"])).toBe(false);
    expect((el as HTMLInputElement).checked).toBe(false);
    el = make(`<form><input type="reset" role="button" value="Add experience" data-t></form>`);
    expect(safeClick(el, ["input"])).toBe(false);
    el = make(`<form><button type="reset" data-t>Add experience</button></form>`);
    expect(safeClick(el, ["button"])).toBe(false);
    document.body.innerHTML = `<label role="button" data-t><input type="checkbox" id="c"> Add experience</label>`;
    el = document.querySelector<HTMLElement>("[data-t]")!;
    expect(safeClick(el, ["label"])).toBe(false);
    expect((document.getElementById("c") as HTMLInputElement).checked).toBe(false);
  });

  test("role=button on div, span and li is clickable", () => {
    for (const tag of ["div", "span", "li"]) {
      expect(safeClick(make(`<${tag} role="button" data-t>Add experience</${tag}>`), [tag])).toBe(true);
    }
  });

  function shadowButton(hostHtml: string, hostSel: string): HTMLElement {
    document.body.innerHTML = hostHtml;
    const host = document.querySelector<HTMLElement>(hostSel)!;
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<button type="button" data-t>Add experience</button>`;
    const el = root.querySelector<HTMLElement>("[data-t]")!;
    el.click = vi.fn();
    return el;
  }

  test("refuses a shadow button whose host sits in a submit button", () => {
    const el = shadowButton(`<form><button type="submit"><span id="h"></span></button></form>`, "#h");
    expect(safeClick(el, ["button"])).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("refuses a shadow button whose host sits in a[href]", () => {
    const el = shadowButton(`<a href="/x"><span id="h"></span></a>`, "#h");
    expect(safeClick(el, ["button"])).toBe(false);
  });

  test("refuses a shadow button whose host sits in a label for a submitter", () => {
    const el = shadowButton(`<form><button type="submit" id="s">x</button></form><label for="s"><span id="h"></span></label>`, "#h");
    expect(safeClick(el, ["button"])).toBe(false);
  });

  test("refuses a shadow button whose host sits in role=link", () => {
    const el = shadowButton(`<div role="link"><span id="h"></span></div>`, "#h");
    expect(safeClick(el, ["button"])).toBe(false);
  });

  test("refuses an element with a shadow root or a custom element tag", () => {
    document.body.innerHTML = `<div role="button" id="h">Add experience</div>`;
    const host = document.getElementById("h")!;
    host.attachShadow({ mode: "open" }).innerHTML = "Submit application";
    host.click = vi.fn();
    expect(safeClick(host, ["div"])).toBe(false);
    expect(host.click).not.toHaveBeenCalled();
    const custom = make(`<my-x role="button" data-t>Add experience</my-x>`);
    expect(safeClick(custom, ["my-x"])).toBe(false);
  });

  function slotted(shadowHtml: string): HTMLElement {
    document.body.innerHTML = `<div id="h"><span role="button" data-t>Add experience</span></div>`;
    document.getElementById("h")!.attachShadow({ mode: "open" }).innerHTML = shadowHtml;
    const el = document.querySelector<HTMLElement>("[data-t]")!;
    el.click = vi.fn();
    return el;
  }

  test("refuses a light-DOM span slotted into a shadow submit button", () => {
    const el = slotted(`<form><button type="submit"><slot></slot></button></form>`);
    expect(safeClick(el, ["span"])).toBe(false);
    expect(el.click).not.toHaveBeenCalled();
  });

  test("refuses a slotted span in a shadow a[href]", () => {
    const el = slotted(`<a href="/x"><slot></slot></a>`);
    expect(safeClick(el, ["span"])).toBe(false);
  });

  test("refuses a slotted span in a shadow label with a checkbox", () => {
    const el = slotted(`<label><input type="checkbox" id="c"><slot></slot></label>`);
    expect(safeClick(el, ["span"])).toBe(false);
    const box = document.getElementById("h")!.shadowRoot!.getElementById("c") as HTMLInputElement;
    expect(box.checked).toBe(false);
  });

  test("refuses a div with a closed shadow root (chrome.dom)", () => {
    document.body.innerHTML = `<div role="button" id="h">Add experience</div>`;
    const host = document.getElementById("h")!;
    const root = host.attachShadow({ mode: "closed" });
    host.click = vi.fn();
    vi.stubGlobal("chrome", { dom: { openOrClosedShadowRoot: (e: Element) => (e === host ? root : null) } });
    try {
      expect(safeClick(host, ["div"])).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
    expect(host.click).not.toHaveBeenCalled();
  });

  test("refuses a div with a closed shadow root (openOrClosedShadowRoot property)", () => {
    document.body.innerHTML = `<div role="button" id="h">Add experience</div>`;
    const host = document.getElementById("h")!;
    const root = host.attachShadow({ mode: "closed" });
    Object.defineProperty(host, "openOrClosedShadowRoot", { value: root });
    host.click = vi.fn();
    expect(safeClick(host, ["div"])).toBe(false);
    expect(host.click).not.toHaveBeenCalled();
  });

  test("refuses a light-DOM child of a closed shadow host", () => {
    document.body.innerHTML = `<div id="h"><button type="button" data-t>Add experience</button></div>`;
    const host = document.getElementById("h")!;
    const root = host.attachShadow({ mode: "closed" });
    vi.stubGlobal("chrome", { dom: { openOrClosedShadowRoot: (e: Element) => (e === host ? root : null) } });
    try {
      expect(safeClick(document.querySelector<HTMLElement>("[data-t]")!, ["button"])).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("refuses a span inside role=checkbox, switch, option and summary", () => {
    for (const outer of ['<div role="checkbox">', '<div role="switch">', '<div role="radio">', '<div role="option">',
      '<div role="menuitemcheckbox">', "<details><summary>", "<summary>"]) {
      const close = outer.startsWith("<details") ? "</summary></details>" : outer.replace("<", "</").replace(/ .*>/, ">");
      const el = make(`${outer}<span role="button" data-t>Add experience</span>${close}`);
      expect(safeClick(el, ["span"])).toBe(false);
    }
  });

  test("a plain light-DOM button in a form is still clicked", () => {
    const el = make(`<form><button type="button" data-t>Add experience</button></form>`);
    expect(safeClick(el, ["button"])).toBe(true);
  });
});
