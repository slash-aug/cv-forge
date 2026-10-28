import { beforeEach, describe, expect, test } from "vitest";
import { countryName, pickOption } from "../src/content/combobox";

/**
 * A react-select stand-in: typing opens a listbox of the options that contain the text,
 * clicking an option shows it as the single value and closes the list.
 */
function widget(id: string, options: string[], opts: { delayMs?: number; extra?: string } = {}): HTMLInputElement {
  const wrap = document.createElement("div");
  wrap.className = "select__container";
  wrap.innerHTML = `<div class="select__control"><div class="select__value-container">
    <div class="select__input-container"><input id="${id}" role="combobox" aria-autocomplete="list"
    aria-expanded="false" value=""></div></div></div>`;
  document.body.append(wrap);
  const input = wrap.querySelector("input") as HTMLInputElement;
  const control = wrap.querySelector(".select__control") as HTMLElement;
  const render = (): void => {
    wrap.querySelector("[role=listbox]")?.remove();
    const text = input.value.toLowerCase();
    if (text === "") return;
    const list = document.createElement("div");
    list.setAttribute("role", "listbox");
    list.id = `${id}-listbox`;
    for (const o of options.filter((x) => x.toLowerCase().includes(text))) {
      const opt = document.createElement("div");
      opt.setAttribute("role", "option");
      opt.textContent = o;
      opt.addEventListener("click", () => {
        control.querySelector(".select__single-value")?.remove();
        const shown = document.createElement("div");
        shown.className = "select__single-value";
        shown.textContent = o;
        control.querySelector(".select__value-container")?.prepend(shown);
        input.value = "";
        list.remove();
        input.removeAttribute("aria-controls");
      });
      list.append(opt);
    }
    if (opts.extra) list.insertAdjacentHTML("beforeend", opts.extra);
    wrap.append(list);
    input.setAttribute("aria-controls", list.id);
    input.setAttribute("aria-expanded", "true");
  };
  input.addEventListener("input", () => {
    if (opts.delayMs) setTimeout(render, opts.delayMs);
    else render();
  });
  return input;
}

const shown = (input: HTMLInputElement): string | undefined =>
  input.closest(".select__control")?.querySelector(".select__single-value")?.textContent ?? undefined;

beforeEach(() => {
  document.body.replaceChildren();
});

describe("pickOption", () => {
  test("types the answer and clicks the exact option", async () => {
    const input = widget("q", ["Yes", "No", "Yes, in the future"]);
    expect(await pickOption(input, "Yes")).toBe("set");
    expect(shown(input)).toBe("Yes");
  });

  test("waits for options that load late (location search)", async () => {
    const input = widget("loc", ["Londrina, Paraná, Brazil", "London, UK"], { delayMs: 300 });
    expect(await pickOption(input, "Londrina", { prefix: true })).toBe("set");
    expect(shown(input)).toBe("Londrina, Paraná, Brazil");
  });

  test("a prefix match needs the prefix option", async () => {
    const input = widget("loc", ["Londrina, Paraná, Brazil"]);
    expect(await pickOption(input, "Londrina")).toBe("nomatch");
    expect(shown(input)).toBeUndefined();
  });

  test("no matching option clears the typed text and reports nomatch", async () => {
    const input = widget("q", ["Maybe"]);
    expect(await pickOption(input, "Yes", { waitMs: 200 })).toBe("nomatch");
    expect(input.value).toBe("");
    expect(shown(input)).toBeUndefined();
  });

  test("an answer that starts with the option word picks it (Yes. I will need a permit...)", async () => {
    const input = widget("q", ["Yes", "No"]);
    expect(await pickOption(input, "Yes. I will need an employment permit.")).toBe("set");
    expect(shown(input)).toBe("Yes");
  });

  test("a dropdown that already shows a value is never changed", async () => {
    const input = widget("q", ["Yes", "No"]);
    await pickOption(input, "No");
    expect(await pickOption(input, "Yes")).toBe("differs");
    expect(shown(input)).toBe("No");
    expect(await pickOption(input, "No")).toBe("same");
  });

  test("never clicks a forward-moving option such as Submit", async () => {
    const input = widget("q", ["Submit application"]);
    expect(await pickOption(input, "Submit application", { waitMs: 200 })).toBe("nomatch");
    expect(shown(input)).toBeUndefined();
  });

  test("never clicks a button or link placed inside the list", async () => {
    let clicked = false;
    const input = widget("q", [], { extra: `<button type="button" role="option" id="b">Yes</button>` });
    input.closest(".select__container")!.addEventListener("click", (e) => {
      if ((e.target as Element).id === "b") clicked = true;
    });
    expect(await pickOption(input, "Yes", { waitMs: 200 })).toBe("nomatch");
    expect(clicked).toBe(false);
  });
});

describe("countryName", () => {
  test("turns an ISO code into its English name", () => {
    expect(countryName("BR")).toBe("Brazil");
    expect(countryName("IE")).toBe("Ireland");
  });

  test("leaves a name or an unknown value as it is", () => {
    expect(countryName("Brazil")).toBe("Brazil");
    expect(countryName("")).toBe("");
  });
});
