import { beforeEach, describe, expect, test } from "vitest";
import {
  attachFile, checkRadio, clearHighlights, highlight, isEmpty, selectOption, setValue,
} from "../src/content/dom";

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("setValue", () => {
  test("fires input and change and works with a React-style tracked setter", () => {
    const el = document.createElement("input");
    document.body.append(el);
    // React shadows the instance value property to track changes.
    let tracked = "";
    Object.defineProperty(el, "value", {
      configurable: true,
      get: () => tracked,
      set: (v: string) => { tracked = v; },
    });
    const seen: string[] = [];
    el.addEventListener("input", (e) => seen.push(`input:${e.bubbles}`));
    el.addEventListener("change", (e) => seen.push(`change:${e.bubbles}`));
    setValue(el, "Ana");
    expect(seen).toEqual(["input:true", "change:true"]);
    // the native setter ran, bypassing the shadowing instance property
    expect(tracked).toBe("");
    const native = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.get!;
    expect(native.call(el)).toBe("Ana");
  });

  test("works on a textarea", () => {
    const el = document.createElement("textarea");
    setValue(el, "hello");
    expect(el.value).toBe("hello");
  });
});

describe("selectOption", () => {
  function select(): HTMLSelectElement {
    const s = document.createElement("select");
    s.innerHTML = '<option value="">Choose</option><option value="br">Brasil</option><option value="pt">Portugal</option>';
    return s;
  }
  test("matches by value or by text, folded", () => {
    const s = select();
    expect(selectOption(s, "PT")).toBe(true);
    expect(s.value).toBe("pt");
    expect(selectOption(s, "  brasil ")).toBe(true);
    expect(s.value).toBe("br");
  });
  test("returns false when nothing matches", () => {
    const s = select();
    expect(selectOption(s, "France")).toBe(false);
    expect(s.value).toBe("");
  });
  test("dispatches change on a match", () => {
    const s = select();
    let n = 0;
    s.addEventListener("change", () => n++);
    selectOption(s, "br");
    expect(n).toBe(1);
  });
});

describe("checkRadio", () => {
  function group(): HTMLInputElement[] {
    document.body.innerHTML =
      '<label><input type="radio" name="r" value="y"> Yes</label>' +
      '<input type="radio" name="r" value="n" id="n"><label for="n">No</label>';
    return [...document.querySelectorAll<HTMLInputElement>("input")];
  }
  test("matches on label text and checks it", () => {
    const g = group();
    expect(checkRadio(g, "no")).toBe(true);
    expect(g[1]!.checked).toBe(true);
    expect(g[0]!.checked).toBe(false);
  });
  test("returns false when nothing matches", () => {
    const g = group();
    expect(checkRadio(g, "maybe")).toBe(false);
    expect(g.some((r) => r.checked)).toBe(false);
  });
});

describe("attachFile", () => {
  test("puts one named file on the input", () => {
    const input = document.createElement("input");
    input.type = "file";
    let changed = 0;
    input.addEventListener("change", () => changed++);
    expect(attachFile(input, "cv.pdf", new Uint8Array([1, 2, 3]).buffer)).toBe(true);
    expect(input.files?.length).toBe(1);
    expect(input.files?.[0]?.name).toBe("cv.pdf");
    expect(changed).toBe(1);
  });
});

describe("isEmpty", () => {
  test("text input, select, checkbox, other", () => {
    const t = document.createElement("input");
    expect(isEmpty(t)).toBe(true);
    t.value = "  ";
    expect(isEmpty(t)).toBe(true);
    t.value = "x";
    expect(isEmpty(t)).toBe(false);
    const s = document.createElement("select");
    s.innerHTML = '<option value="">-</option><option value="a">A</option>';
    expect(isEmpty(s)).toBe(true);
    s.value = "a";
    expect(isEmpty(s)).toBe(false);
    const c = document.createElement("input");
    c.type = "checkbox";
    expect(isEmpty(c)).toBe(true);
    c.checked = true;
    expect(isEmpty(c)).toBe(false);
    const d = document.createElement("div");
    expect(isEmpty(d)).toBe(true);
    d.textContent = "hi";
    expect(isEmpty(d)).toBe(false);
  });
});

describe("highlight", () => {
  test("sets an outline and reason, clearHighlights restores", () => {
    const el = document.createElement("input");
    el.style.outline = "1px solid red";
    document.body.append(el);
    highlight(el, "phone is never filled");
    expect(el.getAttribute("data-cvforge-reason")).toBe("phone is never filled");
    expect(el.style.outline).not.toBe("1px solid red");
    expect(el.style.display).toBe("");
    clearHighlights();
    expect(el.hasAttribute("data-cvforge-reason")).toBe(false);
    expect(el.style.outline).toBe("1px solid red");
  });
});
