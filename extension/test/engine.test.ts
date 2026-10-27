import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fill, type FillDeps } from "../src/fill/engine";
import type { PageMap, QuestionSlot } from "../src/fill/pagemap";
import type { Kit } from "../src/shared/kit";

const html = readFileSync(resolve(__dirname, "fixtures/generic-form.html"), "utf8");
const kitJson = JSON.parse(readFileSync(resolve(__dirname, "fixtures/kit.json"), "utf8")) as Kit;

const $ = <T extends Element>(id: string): T => document.getElementById(id) as unknown as T;
const input = (id: string): HTMLInputElement => $<HTMLInputElement>(id);
const area = (id: string): HTMLTextAreaElement => $<HTMLTextAreaElement>(id);

let kit: Kit;
let suggested: [QuestionSlot, string][];
let deps: FillDeps;

function map(over: Partial<PageMap> = {}): PageMap {
  return {
    source: "guesser",
    fields: [],
    questions: [],
    files: {},
    salary: null,
    phone: [],
    consent: [],
    unplaced: [],
    lists: [],
    allowClicks: [],
    ...over,
  };
}

beforeEach(() => {
  document.body.innerHTML = html;
  kit = structuredClone(kitJson);
  suggested = [];
  deps = {
    pdf: async () => ({ ok: true, value: { name: "cv.pdf", bytes: new ArrayBuffer(8) } }),
    bank: async () => null,
    suggest: (slot, answer) => void suggested.push([slot, answer]),
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fields", () => {
  test("fills empty fields and marks guessed slots as guessed", async () => {
    const s = await fill(
      map({
        fields: [
          { key: "basics.name", el: input("name"), guessed: false },
          { key: "basics.city", el: input("city"), guessed: true },
        ],
      }),
      kit,
      deps,
    );
    expect(input("name").value).toBe("Ana Exemplo");
    expect(input("city").value).toBe("Lisbon");
    expect(s.filled.map((i) => i.label)).toEqual(["Full name"]);
    expect(s.guessed.map((i) => i.label)).toEqual(["City"]);
  });

  test("skips a kit field with an empty value", async () => {
    kit.fields.find((f) => f.key === "basics.city")!.value = "";
    const s = await fill(map({ fields: [{ key: "basics.city", el: input("city"), guessed: false }] }), kit, deps);
    expect(input("city").value).toBe("");
    expect(s.filled).toEqual([]);
    expect(s.needsYou).toEqual([]);
  });

  test("never overwrites a prefilled field that differs; reports it", async () => {
    const s = await fill(map({ fields: [{ key: "basics.email", el: input("email"), guessed: false }] }), kit, deps);
    expect(input("email").value).toBe("old@example.com");
    expect(s.needsYou).toHaveLength(1);
    expect(s.needsYou[0]?.note).toBe("already filled, kit says ana.exemplo@example.com");
    expect(input("email").hasAttribute("data-cvforge-reason")).toBe(true);
  });

  test("a prefilled field equal to the kit is reported as already filled", async () => {
    input("city").value = "lisbon";
    const s = await fill(map({ fields: [{ key: "basics.city", el: input("city"), guessed: false }] }), kit, deps);
    expect(s.filled[0]?.note).toBe("already filled");
    expect(s.needsYou).toEqual([]);
  });

  test("a select with no matching option goes to needsYou", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      `<select id="country"><option value="">Choose</option><option value="BR">Brazil</option></select>`,
    );
    const sel = $<HTMLSelectElement>("country");
    const s = await fill(map({ fields: [{ key: "basics.country", el: sel, guessed: false }] }), kit, deps);
    expect(sel.value).toBe("");
    expect(s.needsYou).toHaveLength(1);
    expect(sel.hasAttribute("data-cvforge-reason")).toBe(true);
  });

  test("fills a radio group by label", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      `<label><input type="radio" name="n" value="a"> 30 days</label><label><input type="radio" name="n" value="b"> 90 days</label>`,
    );
    const group = [...document.querySelectorAll<HTMLInputElement>("input[name=n]")];
    const s = await fill(map({ fields: [{ key: "prefs.notice", el: group, guessed: false }] }), kit, deps);
    expect(group.map((r) => r.checked)).toEqual([true, false]);
    expect(s.filled).toHaveLength(1);
  });
});

describe("questions", () => {
  test("fills kit answers; bank hit is suggested, not filled", async () => {
    deps.bank = async () => ({ question: "Are you a robot?", answer: "No" });
    const q1: QuestionSlot = { label: "Why do you want to work here?", el: area("q1"), maxLength: null };
    const q3: QuestionSlot = { label: "Are you a robot?", el: area("q3"), maxLength: null };
    const s = await fill(map({ questions: [q1, q3] }), kit, deps);
    expect(area("q1").value).toBe("I like the product.");
    expect(area("q3").value).toBe("");
    expect(suggested).toEqual([[q3, "No"]]);
    expect(s.suggested).toHaveLength(1);
    expect(s.filled).toHaveLength(1);
  });

  test("no kit answer and no bank hit goes to needsYou", async () => {
    const q4: QuestionSlot = { label: "Favourite colour?", el: area("q4"), maxLength: null };
    const s = await fill(map({ questions: [q4] }), kit, deps);
    expect(s.needsYou).toHaveLength(1);
    expect(area("q4").hasAttribute("data-cvforge-reason")).toBe(true);
  });

  test("question answer longer than maxlength is not filled", async () => {
    const q2: QuestionSlot = { label: "Why do you want to work here?", el: area("q2"), maxLength: 10 };
    const s = await fill(map({ questions: [q2] }), kit, deps);
    expect(area("q2").value).toBe("");
    expect(s.needsYou[0]?.note).toBe("answer longer than limit");
    expect(area("q2").hasAttribute("data-cvforge-reason")).toBe(true);
  });

  test("a non-empty question is not overwritten", async () => {
    area("q1").value = "my own text";
    const q1: QuestionSlot = { label: "Why do you want to work here?", el: area("q1"), maxLength: null };
    const s = await fill(map({ questions: [q1] }), kit, deps);
    expect(area("q1").value).toBe("my own text");
    expect(s.needsYou).toHaveLength(1);
  });
});

describe("never filled", () => {
  test("phone highlighted, never filled", async () => {
    const s = await fill(map({ phone: [input("phone")] }), kit, deps);
    expect(input("phone").value).toBe("");
    expect(input("phone").hasAttribute("data-cvforge-reason")).toBe(true);
    expect(s.needsYou[0]?.note).toBe("phone: fill by hand");
  });

  test("consent never ticked", async () => {
    const s = await fill(map({ consent: [input("consent")] }), kit, deps);
    expect(input("consent").checked).toBe(false);
    expect(input("consent").hasAttribute("data-cvforge-reason")).toBe(true);
    expect(s.needsYou).toHaveLength(1);
  });

  test("an unplaced combobox says to pick from the list", async () => {
    input("mystery").setAttribute("role", "combobox");
    const s = await fill(map({ unplaced: [input("mystery")] }), kit, deps);
    expect(s.needsYou[0]?.note).toBe("pick from the list by hand");
  });

  test("unplaced elements are highlighted and reported", async () => {
    const s = await fill(map({ unplaced: [input("mystery")] }), kit, deps);
    expect(input("mystery").hasAttribute("data-cvforge-reason")).toBe(true);
    expect(s.needsYou).toHaveLength(1);
  });
});

describe("salary", () => {
  const slot = (currency: string | null, period: "year" | "month" | "hour" | null) => ({
    el: input("salary"),
    currency,
    period,
  });

  test("unconfirmed salary not filled", async () => {
    kit.salary!.confirmed = false;
    const s = await fill(map({ salary: slot(null, null) }), kit, deps);
    expect(input("salary").value).toBe("");
    expect(s.needsYou[0]?.note).toBe("salary unconfirmed");
  });

  test("null kit salary not filled", async () => {
    kit.salary = null;
    const s = await fill(map({ salary: slot(null, null) }), kit, deps);
    expect(input("salary").value).toBe("");
    expect(s.needsYou[0]?.note).toBe("salary unconfirmed");
  });

  test("salary currency mismatch not filled", async () => {
    const s = await fill(map({ salary: slot("USD", "year") }), kit, deps);
    expect(input("salary").value).toBe("");
    expect(s.needsYou[0]?.note).toBe("salary wants USD/year");
  });

  test("salary period mismatch not filled", async () => {
    const s = await fill(map({ salary: slot("EUR", "month") }), kit, deps);
    expect(input("salary").value).toBe("");
    expect(s.needsYou[0]?.note).toBe("salary wants EUR/month");
  });

  test("salary select with no matching option: pick by hand", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<select id="salsel"><option value="">Choose</option><option>Up to 10000</option></select>',
    );
    const el = $<HTMLSelectElement>("salsel");
    const s = await fill(map({ salary: { el, currency: null, period: null } }), kit, deps);
    expect(el.value).toBe("");
    expect(s.needsYou[0]?.note).toBe("salary: pick by hand");
  });

  test("confirmed matching salary filled as whole number", async () => {
    kit.salary!.amount = 60000.4;
    await fill(map({ salary: slot("EUR", "year") }), kit, deps);
    expect(input("salary").value).toBe("60000");
  });
});

describe("files", () => {
  test("attaches the CV", async () => {
    const s = await fill(map({ files: { cv: input("cv") } }), kit, deps);
    expect(input("cv").files?.length).toBe(1);
    expect(s.attached).toHaveLength(1);
  });

  test("missing pdf -> attach manually with file name", async () => {
    deps.pdf = async () => ({ ok: false, error: { kind: "down" } });
    const s = await fill(map({ files: { cv: input("cv") } }), kit, deps);
    expect(input("cv").files?.length ?? 0).toBe(0);
    expect(s.needsYou[0]?.note).toBe("attach manually: cv.pdf");
  });

  test("attachFile failure -> attach manually", async () => {
    vi.spyOn(input("cv"), "files", "set").mockImplementation(() => {});
    const s = await fill(map({ files: { cv: input("cv") } }), kit, deps);
    expect(s.needsYou[0]?.note).toBe("attach manually: cv.pdf");
  });

  test("no CV pdf in kit", async () => {
    kit.links.cv_pdf = null;
    const s = await fill(map({ files: { cv: input("cv") } }), kit, deps);
    expect(s.needsYou[0]?.note).toBe("no CV PDF in kit");
  });

  test("no letter in kit leaves the letter input alone", async () => {
    const s = await fill(map({ files: { letter: input("letter") } }), kit, deps);
    expect(input("letter").files?.length ?? 0).toBe(0);
    expect(s.needsYou).toEqual([]);
  });
});

describe("lists", () => {
  function listFor(kind: "languages", opts: { add?: boolean; open?: boolean } = {}) {
    const host = document.createElement("div");
    document.body.append(host);
    const addEntry = (): HTMLElement => {
      const e = document.createElement("div");
      e.innerHTML = `<input class="lang">`;
      host.append(e);
      return e;
    };
    const openSpy = vi.fn(async () => addEntry());
    const slot = {
      kind,
      existing: () => [...host.children] as HTMLElement[],
      add: opts.add ? { button: "#add" } : undefined,
      openEntry: opts.open ? openSpy : undefined,
      fillEntry: (entry: HTMLElement, item: unknown) => {
        const el = entry.querySelector<HTMLInputElement>(".lang")!;
        if (el.value === "") el.value = (item as { name: string }).name;
        return { filled: [{ label: "Language", el }], needsYou: [] };
      },
    };
    return { host, slot, openSpy };
  }

  test("opens a new entry when none exists and add is defined", async () => {
    const { host, slot, openSpy } = listFor("languages", { add: true, open: true });
    await fill(map({ lists: [slot] }), kit, deps);
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(host.querySelector<HTMLInputElement>(".lang")!.value).toBe("English");
  });

  test("without add, the entry is left for the user", async () => {
    const { host, slot, openSpy } = listFor("languages");
    const s = await fill(map({ lists: [slot] }), kit, deps);
    expect(openSpy).not.toHaveBeenCalled();
    expect(host.children).toHaveLength(0);
    expect(s.needsYou[0]?.note).toBe("add languages entry by hand");
  });

  test("an existing entry is filled, not duplicated", async () => {
    const { host, slot, openSpy } = listFor("languages", { add: true, open: true });
    host.innerHTML = `<div><input class="lang"></div>`;
    await fill(map({ lists: [slot] }), kit, deps);
    expect(openSpy).not.toHaveBeenCalled();
    expect(host.children).toHaveLength(1);
    expect(host.querySelector<HTMLInputElement>(".lang")!.value).toBe("English");
  });
});

describe("second fill", () => {
  test("no re-attach, no duplicate list entries, no overwrite", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const slot = {
      kind: "languages" as const,
      existing: () => [...host.children] as HTMLElement[],
      add: { button: "#add" },
      openEntry: async () => {
        const e = document.createElement("div");
        e.innerHTML = `<input class="lang">`;
        host.append(e);
        return e;
      },
      fillEntry: (entry: HTMLElement, item: unknown) => {
        const el = entry.querySelector<HTMLInputElement>(".lang")!;
        if (el.value === "") el.value = (item as { name: string }).name;
        return { filled: [{ label: "Language", el }], needsYou: [] };
      },
    };
    const pdf = vi.fn(deps.pdf);
    deps.pdf = pdf;
    const m = (): PageMap =>
      map({
        fields: [
          { key: "basics.name", el: input("name"), guessed: false },
          { key: "basics.email", el: input("email"), guessed: false },
        ],
        files: { cv: input("cv") },
        lists: [slot],
      });
    await fill(m(), kit, deps);
    input("name").value = "Edited By Hand";
    const s2 = await fill(m(), kit, deps);
    expect(pdf).toHaveBeenCalledTimes(1);
    expect(host.children).toHaveLength(1);
    expect(input("name").value).toBe("Edited By Hand");
    expect(input("email").value).toBe("old@example.com");
    expect(s2.attached[0]?.note).toBe("already attached");
  });
});

describe("clicks", () => {
  test("guesser-sourced fill clicks nothing", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      `<select id="country"><option value="">Choose</option><option value="PT">PT</option></select>
       <label><input type="radio" name="n" value="a"> 30 days</label><label><input type="radio" name="n" value="b"> 90 days</label>`,
    );
    const click = vi.spyOn(HTMLElement.prototype, "click");
    await fill(
      map({
        fields: [
          { key: "basics.name", el: input("name"), guessed: true },
          { key: "basics.country", el: $<HTMLSelectElement>("country"), guessed: false },
          { key: "prefs.notice", el: [...document.querySelectorAll<HTMLInputElement>("input[name=n]")], guessed: false },
        ],
        questions: [{ label: "Why do you want to work here?", el: area("q1"), maxLength: null }],
        files: { cv: input("cv") },
        salary: { el: input("salary"), currency: null, period: null },
        phone: [input("phone")],
        consent: [input("consent")],
        unplaced: [input("mystery")],
      }),
      kit,
      deps,
    );
    expect(click).toHaveBeenCalledTimes(0);
  });
});

describe("review fixes", () => {
  const q1 = (): QuestionSlot => ({ label: "Why do you want to work here?", el: area("q1"), maxLength: null });
  const hl = (id: string): boolean => $(id).hasAttribute("data-cvforge-reason");

  test("non-empty question with no kit answer is reported as already filled, bank not asked", async () => {
    area("q4").value = "blue";
    const bank = vi.fn(async () => null);
    deps.bank = bank;
    const s = await fill(map({ questions: [{ label: "Favourite colour?", el: area("q4"), maxLength: null }] }), kit, deps);
    expect(bank).not.toHaveBeenCalled();
    expect(s.filled).toEqual([{ label: "Favourite colour?", el: area("q4"), note: "already filled" }]);
  });

  const base = () => ({ phone: [input("phone")], consent: [input("consent")] });
  const guarded = (s: Awaited<ReturnType<typeof fill>>): void => {
    expect(hl("phone")).toBe(true);
    expect(hl("consent")).toBe(true);
    expect(s.needsYou.length).toBeGreaterThanOrEqual(3);
  };

  test("bank rejection does not abort the fill", async () => {
    deps.bank = async () => { throw new Error("secret detail"); };
    const q4: QuestionSlot = { label: "Favourite colour?", el: area("q4"), maxLength: null };
    const s = await fill(map({ ...base(), questions: [q4] }), kit, deps);
    guarded(s);
    expect(s.needsYou.map((i) => i.note)).toContain("could not fill: Favourite colour?");
    expect(JSON.stringify(s.needsYou)).not.toContain("secret");
  });

  test("pdf throwing does not abort the fill", async () => {
    deps.pdf = async () => { throw new Error("boom"); };
    const s = await fill(map({ ...base(), files: { cv: input("cv") } }), kit, deps);
    guarded(s);
    expect(s.needsYou.map((i) => i.note)).toContain("could not fill: CV");
  });

  test("fillEntry throwing does not abort the fill", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    host.innerHTML = "<div></div>";
    const slot = {
      kind: "languages" as const,
      existing: () => [...host.children] as HTMLElement[],
      fillEntry: () => { throw new Error("boom"); },
    };
    const s = await fill(map({ ...base(), lists: [slot] }), kit, deps);
    guarded(s);
    expect(s.needsYou.map((i) => i.note)).toContain("could not fill: languages 1");
  });

  test("openEntry throwing does not abort the fill", async () => {
    const slot = {
      kind: "languages" as const,
      existing: () => [],
      add: { button: "#add" },
      openEntry: async () => { throw new Error("boom"); },
      fillEntry: () => ({ filled: [], needsYou: [] }),
    };
    const s = await fill(map({ ...base(), lists: [slot] }), kit, deps);
    guarded(s);
  });

  test("after openEntry returns null once, it is not called again for that list", async () => {
    kit.languages.push({ key: "languages.1", name: "Spanish", detail: "Basic" });
    kit.languages.push({ key: "languages.2", name: "French", detail: "Basic" });
    const host = document.createElement("div");
    document.body.append(host);
    let calls = 0;
    const slot = {
      kind: "languages" as const,
      existing: () => [...host.children] as HTMLElement[],
      add: { button: "#add" },
      openEntry: async () => {
        calls++;
        if (calls === 1) return null;
        const e = document.createElement("div");
        e.innerHTML = `<input class="lang">`;
        host.append(e);
        return e;
      },
      fillEntry: (entry: HTMLElement, item: unknown) => {
        entry.querySelector<HTMLInputElement>(".lang")!.value = (item as { name: string }).name;
        return { filled: [], needsYou: [] };
      },
    };
    const s = await fill(map({ lists: [slot] }), kit, deps);
    expect(calls).toBe(1);
    expect(host.children).toHaveLength(0);
    expect(s.needsYou.map((i) => i.note)).toEqual(Array(3).fill("add languages entry by hand"));
  });

  test("fillEntry result is routed into filled and needsYou", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    host.innerHTML = `<div></div>`;
    const slot = {
      kind: "languages" as const,
      existing: () => [...host.children] as HTMLElement[],
      fillEntry: () => ({
        filled: [{ label: "a", el: null }],
        needsYou: [{ label: "b", el: null, note: "n" }],
      }),
    };
    const s = await fill(map({ lists: [slot] }), kit, deps);
    expect(s.filled).toEqual([{ label: "a", el: null }]);
    expect(s.needsYou).toEqual([{ label: "b", el: null, note: "n" }]);
  });
});
