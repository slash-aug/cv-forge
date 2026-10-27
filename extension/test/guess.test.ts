import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fill, type FillDeps } from "../src/fill/engine";
import type { FieldKey, PageMap } from "../src/fill/pagemap";
import { guessPage, looksLikeApplication } from "../src/guesser/guess";
import type { Kit } from "../src/shared/kit";

const fixture = (name: string): string => readFileSync(resolve(__dirname, "fixtures", name), "utf8");
const kitJson = JSON.parse(fixture("kit.json")) as Kit;
const $ = (id: string): HTMLElement => document.getElementById(id) as HTMLElement;
const slotFor = (m: PageMap, key: FieldKey) => m.fields.find((f) => f.key === key);
const elFor = (m: PageMap, key: FieldKey) => slotFor(m, key)?.el;

let clicks: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  clicks = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => vi.restoreAllMocks());

describe("EN form", () => {
  beforeEach(() => void (document.body.innerHTML = fixture("guess-en.html")));

  test("first/last/email/city/linkedin placed as guessed; phone to phone; consent to consent", () => {
    const m = guessPage(document);
    expect(m.source).toBe("guesser");
    expect(elFor(m, "basics.first_name")).toBe($("fn"));
    expect(elFor(m, "basics.last_name")).toBe($("ln"));
    expect(elFor(m, "basics.email")).toBe(document.querySelector("[name=contact]"));
    expect(elFor(m, "basics.city")).toBe($("c"));
    expect(elFor(m, "basics.linkedin")).toBe($("li"));
    expect(m.fields.every((f) => f.guessed)).toBe(true);
    expect(m.phone).toEqual([$("ph")]);
    expect(m.consent).toEqual([$("cons")]);
    expect(m.files.cv).toBe($("cvf"));
    expect(m.files.letter).toBe($("clf"));
  });

  test("salary slot has the control; no hint means null currency and period", () => {
    const m = guessPage(document);
    expect(m.salary?.el).toBe($("sal"));
    expect(m.salary?.currency).toBeNull();
    expect(m.salary?.period).toBeNull();
  });

  test("ambiguous control stays unplaced", () => {
    const m = guessPage(document);
    expect(m.unplaced).toContain($("amb"));
    expect(m.fields.some((f) => f.el === $("amb"))).toBe(false);
    expect(m.questions.some((q) => q.el === $("amb"))).toBe(false);
  });

  test("textarea with max characters is a question with maxLength", () => {
    const q = guessPage(document).questions.find((x) => x.el === $("why"));
    expect(q?.maxLength).toBe(500);
    expect(q?.label).toBe("Why Example Corp?");
  });

  test("hidden, readonly and disabled controls are ignored", () => {
    const m = guessPage(document);
    const seen = new Set<unknown>([
      ...m.fields.map((f) => f.el),
      ...m.questions.map((q) => q.el),
      ...m.unplaced,
    ]);
    for (const id of ["hid", "ro", "dis"]) expect(seen.has($(id))).toBe(false);
    expect(seen.has(document.querySelector("[name=csrf]"))).toBe(false);
  });

  test("a bare Name beside a Last name becomes first_name", () => {
    document.body.innerHTML = `<label for=a>Name</label><input id=a><label for=b>Last name</label><input id=b>`;
    const m = guessPage(document);
    expect(elFor(m, "basics.first_name")).toBe($("a"));
    expect(elFor(m, "basics.last_name")).toBe($("b"));
  });
});

describe("PT form", () => {
  beforeEach(() => void (document.body.innerHTML = fixture("guess-pt.html")));

  test("nome/sobrenome/e-mail/cidade placed; salary BRL monthly", () => {
    const m = guessPage(document);
    expect(elFor(m, "basics.first_name")).toBe($("nome"));
    expect(elFor(m, "basics.last_name")).toBe($("sobrenome"));
    expect(elFor(m, "basics.email")).toBe($("em"));
    expect(elFor(m, "basics.city")).toBe($("cid"));
    expect(m.phone).toEqual([$("tel")]);
    expect(m.salary?.el).toBe($("sal"));
    expect(m.salary?.currency).toBe("BRL");
    expect(m.salary?.period).toBe("month");
    expect(m.files.cv).toBe($("cv"));
    expect(m.files.letter).toBe($("carta"));
  });

  test("até 500 caracteres gives maxLength 500", () => {
    const q = guessPage(document).questions.find((x) => x.el === $("sobre"));
    expect(q?.maxLength).toBe(500);
  });

  test("radio group becomes one slot; consent checkbox goes to consent, radios never", () => {
    const m = guessPage(document);
    const radios = [...document.querySelectorAll<HTMLInputElement>("[name=visto]")];
    expect(elFor(m, "prefs.visa")).toEqual(radios);
    expect(m.consent).toEqual([document.querySelector("[name=lgpd]")]);
  });
});

describe("hints and visibility", () => {
  test("currency and period come from the legend or parent text, capped at 200 chars", () => {
    document.body.innerHTML = `<fieldset><legend>Salary in EUR per year</legend><input id=s aria-label="Salary"></fieldset>`;
    const m = guessPage(document);
    expect(m.salary?.currency).toBe("EUR");
    expect(m.salary?.period).toBe("year");
    document.body.innerHTML = `<div>${"x ".repeat(120)} USD<input id=s aria-label="Salary"></div>`;
    expect(guessPage(document).salary?.currency).toBeNull();
  });

  test("aria-hidden ancestors and visibility:hidden are skipped", () => {
    document.body.innerHTML = `<div aria-hidden="true"><label for=a>City</label><input id=a></div>
      <div style="visibility:hidden"><label for=b>Cidade</label><input id=b></div>
      <div hidden><label for=c>Country</label><input id=c></div>`;
    const m = guessPage(document);
    expect(m.fields).toEqual([]);
    expect(m.unplaced).toEqual([]);
  });

  test("autocomplete tokens count as exact", () => {
    document.body.innerHTML = `<input id=a autocomplete="given-name"><input id=b autocomplete="family-name">`;
    const m = guessPage(document);
    expect(elFor(m, "basics.first_name")).toBe($("a"));
    expect(elFor(m, "basics.last_name")).toBe($("b"));
  });
});

describe("looksLikeApplication", () => {
  test("false for a newsletter email only", () => {
    document.body.innerHTML = fixture("not-a-form.html");
    expect(looksLikeApplication(document)).toBe(false);
  });
  test("true for email plus name", () => {
    document.body.innerHTML = fixture("guess-en.html");
    expect(looksLikeApplication(document)).toBe(true);
  });
  test("true for a file input hinting at a CV", () => {
    document.body.innerHTML = `<label for=f>Currículo</label><input id=f type=file>`;
    expect(looksLikeApplication(document)).toBe(true);
  });
  test("a .pdf accept alone is not a CV hint", () => {
    document.body.innerHTML = `<label for=f>Passport scan</label><input id=f type=file accept=".pdf">
      <label for=e>Email</label><input id=e type=email>`;
    expect(looksLikeApplication(document)).toBe(false);
    expect(guessPage(document).files.cv).toBeUndefined();
    expect(guessPage(document).unplaced).toContain($("f"));
  });
  test("false for an unrelated file input", () => {
    document.body.innerHTML = `<label for=f>Profile photo</label><input id=f type=file accept="image/*">`;
    expect(looksLikeApplication(document)).toBe(false);
  });
});

describe("review fixes", () => {
  const put = (html: string): PageMap => {
    document.body.innerHTML = html;
    return guessPage(document);
  };

  test("textareas that mention keywords are still questions", () => {
    const m = put(`<label for=a>Why would you relocate?</label><textarea id=a></textarea>
      <label for=b>Describe your visa situation</label><textarea id=b></textarea>`);
    expect(m.questions.map((q) => q.el)).toEqual([$("a"), $("b")]);
    expect(m.unplaced).toEqual([]);
    expect(m.fields).toEqual([]);
  });

  test("a textarea whose signals tie between two keys is still a question", () => {
    const m = put(`<label for=a>Visa and relocation</label><textarea id=a></textarea>
      <label for=b>Notice period</label><textarea id=b name="city_notes"></textarea>`);
    expect(m.questions.map((q) => q.el)).toEqual([$("a"), $("b")]);
    expect(m.unplaced).toEqual([]);
  });

  test("file hints see through underscores and hyphens in name and id", () => {
    const m = put(`<input type=file name="cv_file"><input type=file id="cover-letter-upload">
      <input type=file name="resume_upload">`);
    expect(m.files.cv).toBe(document.querySelector("[name=cv_file]"));
    expect(m.files.letter).toBe($("cover-letter-upload"));
    expect(m.unplaced).toEqual([document.querySelector("[name=resume_upload]")]);
  });

  test("modifiers stop generic keywords", () => {
    const m = put(`<label for=a>Company name</label><input id=a>
      <label for=b>Company website</label><input id=b>
      <label for=c>Nome da empresa</label><input id=c>
      <label for=d>Reference name</label><input id=d>`);
    expect(m.fields).toEqual([]);
    expect(m.questions.map((q) => q.el)).toEqual([$("a"), $("b"), $("c"), $("d")]);
  });

  test("disabled fieldset, inert step, closed details are skipped", () => {
    const m = put(`<fieldset disabled><label for=a>City</label><input id=a></fieldset>
      <div inert><label for=b>Country</label><input id=b></div>
      <details><summary>More</summary><label for=c>Cidade</label><input id=c></details>
      <details open><summary>Open</summary><label for=d>State</label><input id=d></details>`);
    expect(m.fields.map((f) => f.el)).toEqual([$("d")]);
    expect(m.unplaced).toEqual([]);
  });

  test("search, one-time-code and password inputs are ignored", () => {
    const m = put(`<input id=a type=search aria-label="Search jobs"><div role="search"><input id=b aria-label="City"></div>
      <input id=c autocomplete="one-time-code" aria-label="Code"><input id=d type=password aria-label="Password">`);
    expect([...m.fields, ...m.questions, ...m.unplaced]).toEqual([]);
  });

  test("letter hint uses word boundaries", () => {
    const m = put(`<label for=a>Recover</label><input id=a type=file><label for=b>Cartão</label><input id=b type=file>`);
    expect(m.files.letter).toBeUndefined();
    expect(m.unplaced).toEqual([$("a"), $("b")]);
  });

  test("phone variants", () => {
    const m = put(`<input id=a type=tel><input id=b autocomplete="section-x shipping tel">
      <label for=c>Celular</label><input id=c><label for=d>WhatsApp</label><input id=d>`);
    expect(m.phone).toEqual([$("a"), $("b"), $("c"), $("d")]);
  });
});

describe("end to end", () => {
  test("guessPage then fill never clicks, and allowClicks and lists are empty", async () => {
    document.body.innerHTML = fixture("guess-en.html");
    const m = guessPage(document);
    expect(m.allowClicks).toEqual([]);
    expect(m.lists).toEqual([]);
    const deps: FillDeps = {
      pdf: async () => ({ ok: true, value: { name: "cv.pdf", bytes: new ArrayBuffer(8) } }),
      bank: async () => null,
      suggest: () => undefined,
    };
    const s = await fill(m, structuredClone(kitJson), deps);
    expect(($("c") as HTMLInputElement).value).toBe("Lisbon");
    expect(s.guessed.length).toBeGreaterThan(0);
    expect(s.needsYou.some((i) => i.el === $("cons"))).toBe(true);
    expect(($("cons") as HTMLInputElement).checked).toBe(false);
    expect(($("ph") as HTMLInputElement).value).toBe("");
    expect(clicks).toHaveBeenCalledTimes(0);
  });
});

describe("comboboxes", () => {
  test("searchable comboboxes are unplaced, never fields or questions", async () => {
    document.body.innerHTML = `<form>
      <label for="c1">City</label><input id="c1" role="combobox">
      <label for="c2">Country</label><input id="c2" aria-autocomplete="list">
      <label for="c3">Which team interests you?</label><input id="c3" aria-haspopup="listbox">
      <label for="c4">Email</label><input id="c4" type="email" aria-autocomplete="both"></form>`;
    const m = guessPage(document);
    expect(m.fields).toEqual([]);
    expect(m.questions).toEqual([]);
    expect(m.unplaced).toEqual([$("c1"), $("c2"), $("c3"), $("c4")]);
    const s = await fill(m, kitJson, {
      pdf: async () => ({ ok: false, error: { kind: "down" } }),
      bank: async () => null,
      suggest: () => undefined,
    });
    expect(s.needsYou.map((n) => n.note)).toEqual(Array(4).fill("pick from the list by hand"));
    expect(($("c1") as HTMLInputElement).value).toBe("");
  });
});

describe("consent radio groups", () => {
  const deps: FillDeps = {
    pdf: async () => ({ ok: false, error: { kind: "down" } }),
    bank: async () => ({ question: "I agree to the privacy policy", answer: "Yes" }),
    suggest: () => undefined,
  };
  const kit = (): Kit => ({
    ...kitJson,
    answers: [{ question: "I agree to the privacy policy", answer: "Yes", limit: null }],
  });

  test("a legend that reads as consent sends every radio to consent", async () => {
    document.body.innerHTML = `<form><fieldset><legend>I agree to the privacy policy</legend>
      <label><input type="radio" name="pp" id="y" value="yes">Yes</label>
      <label><input type="radio" name="pp" id="n" value="no">No</label></fieldset></form>`;
    const m = guessPage(document);
    expect(m.consent).toEqual([$("y"), $("n")]);
    expect(m.fields).toEqual([]);
    expect(m.questions).toEqual([]);
    await fill(m, kit(), deps);
    expect(($("y") as HTMLInputElement).checked).toBe(false);
    expect(($("n") as HTMLInputElement).checked).toBe(false);
  });

  test("a radiogroup label that reads as consent does too", async () => {
    document.body.innerHTML = `<form><div role="radiogroup" aria-labelledby="gl">
      <span id="gl">I agree to the privacy policy</span>
      <label><input type="radio" name="pp" id="y" value="yes">Yes</label>
      <label><input type="radio" name="pp" id="n" value="no">No</label></div></form>`;
    const m = guessPage(document);
    expect(m.consent).toEqual([$("y"), $("n")]);
    expect(m.questions).toEqual([]);
    await fill(m, kit(), deps);
    expect(($("y") as HTMLInputElement).checked).toBe(false);
    expect(($("n") as HTMLInputElement).checked).toBe(false);
  });
});
