import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { adapterFor } from "../src/adapters/registry";
import { greenhouse } from "../src/adapters/greenhouse";
import { fill, type FillDeps } from "../src/fill/engine";
import type { PageMap } from "../src/fill/pagemap";
import type { Kit } from "../src/shared/kit";

const fixture = (name: string): string => readFileSync(resolve(__dirname, "fixtures", name), "utf8");
const baseKit = JSON.parse(fixture("kit.json")) as Kit;
const kit: Kit = {
  ...baseKit,
  links: { ...baseKit.links, cv_pdf: "cv.pdf" },
  fields: [
    ...baseKit.fields,
    { key: "basics.linkedin", label: "LinkedIn", value: "https://linkedin.com/in/ana-exemplo", group: "links" },
    { key: "basics.portfolio", label: "Website", value: "https://ana.example.com", group: "links" },
  ],
  answers: [
    { question: "Why Example Corp?", answer: "I like the product.", limit: 500 },
    { question: "Will you require visa sponsorship now or in the future?", answer: "No", limit: null },
    { question: "Can you work from our Lisbon office two days a week?", answer: "Yes", limit: null },
  ],
};
const $ = (sel: string): HTMLElement => document.querySelector(sel) as HTMLElement;
const val = (sel: string): string => ($(sel) as HTMLInputElement).value;

const deps = (): FillDeps => ({
  pdf: async () => ({ ok: true, value: { name: "cv.pdf", bytes: new ArrayBuffer(4) } }),
  bank: async () => null,
  suggest: () => undefined,
});

const url = (u: string): URL => new URL(u);

let clicks: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  clicks = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("jobId mirrors the Python site_job_id Greenhouse rows", () => {
  test.each([
    ["https://boards.greenhouse.io/exampleco/jobs/4012345", "4012345"],
    ["https://job-boards.greenhouse.io/exampleco/jobs/4012345?gh_src=x", "4012345"],
    ["https://boards.greenhouse.io/exampleco/jobs/4012345/", "4012345"],
    ["https://boards.greenhouse.io/embed/job_app?for=exampleco&token=4012345", "4012345"],
    ["https://careers.example.com/open-roles?gh_jid=4012345", "4012345"],
    ["https://boards.greenhouse.io/exampleco/jobs/abc", null],
    ["https://careers.example.com/x?gh_jid=abc", null],
    ["https://careers.example.com/x?gh_jid=", null],
    ["https://boards.greenhouse.io/embed/job_app?for=exampleco&token=abc", null],
    ["https://evil.example.com/exampleco/jobs/4012345", null],
    ["https://jobs.example.com/senior", null],
    ["https://boards.greenhouse.io./x/jobs/1", "1"],
    ["https://www.linkedin.com/jobs/view/4012345?gh_jid=4012345", null],
    ["https://jobs.linkedin.com/x?gh_jid=4012345", null],
  ])("%s -> %s", (u, expected) => {
    expect(greenhouse.jobId(url(u), document)).toBe(expected);
  });
});

describe("classic form", () => {
  let map: PageMap;
  beforeEach(() => {
    document.body.innerHTML = fixture("greenhouse-classic.html");
    map = greenhouse.map(document);
  });

  test("map is an adapter map and says so", () => {
    expect(map.source).toBe("adapter");
    expect(map.adapter).toBe("greenhouse");
    expect(map.fields.every((f) => !f.guessed)).toBe(true);
    expect(map.allowClicks).toEqual([]);
  });

  test("fill puts the kit into the expected ids", async () => {
    await fill(map, kit, deps());
    expect(val("#first_name")).toBe("Ana");
    expect(val("#last_name")).toBe("Exemplo");
    expect(val("#email")).toBe("ana.exemplo@example.com");
    expect(val("#job_application_location")).toBe("Lisbon");
    expect(val("#job_application_answers_attributes_0_text_value")).toBe("https://linkedin.com/in/ana-exemplo");
    expect(val("#job_application_answers_attributes_1_text_value")).toBe("https://ana.example.com");
    expect(val("#job_application_answers_attributes_2_text_value")).toBe("https://github.com/ana-exemplo");
    expect(val("#job_application_answers_attributes_4_text_value")).toBe("I like the product.");
    const visa = $("#job_application_answers_attributes_5_answer_selected_options_attributes_5_question_option_id");
    expect((visa as HTMLSelectElement).selectedOptions[0]?.text).toBe("No");
    expect(($("#job_application_answers_attributes_6_boolean_value_1") as HTMLInputElement).checked).toBe(true);
    expect((($("#resume") as HTMLInputElement).files?.length)).toBe(1);
  });

  test("phone, consent, Twitter and unknown questions are left for the user", async () => {
    const summary = await fill(map, kit, deps());
    expect(val("#phone")).toBe("");
    expect(($("#gdpr_processing_consent_given") as HTMLInputElement).checked).toBe(false);
    expect(val("#job_application_answers_attributes_3_text_value")).toBe("");
    expect(val("#job_application_answers_attributes_7_text_value")).toBe("");
    expect(map.phone).toEqual([$("#phone")]);
    expect(map.consent).toEqual([$("#gdpr_processing_consent_given")]);
    const needs = summary.needsYou.map((n) => n.el);
    for (const sel of ["#phone", "#gdpr_processing_consent_given", "#job_application_answers_attributes_3_text_value", "#job_application_answers_attributes_7_text_value"]) {
      expect(needs).toContain($(sel));
    }
  });

  test("question labels are clean and carry maxlength", () => {
    const why = map.questions.find((q) => q.el === $("#job_application_answers_attributes_4_text_value"));
    expect(why).toMatchObject({ label: "Why Example Corp?", maxLength: 500 });
    const lisbon = map.questions.find((q) => Array.isArray(q.el));
    expect(lisbon?.label).toBe("Can you work from our Lisbon office two days a week?");
  });

  test("EEO selects are untouched and listed under needs you", async () => {
    const summary = await fill(map, kit, deps());
    for (const id of ["gender", "hispanic_ethnicity", "veteran_status", "disability_status"]) {
      const el = $(`#job_application_${id}`);
      expect((el as HTMLSelectElement).value).toBe("");
      expect(map.unplaced).toContain(el);
      expect(summary.needsYou.map((n) => n.el)).toContain(el);
    }
  });

  test("hidden latitude, the resume text areas and the submit button are not mapped", () => {
    const seen = new Set<unknown>([
      ...map.fields.map((f) => f.el), ...map.questions.map((q) => q.el), ...map.unplaced,
      ...map.consent, ...map.phone, map.files.cv, map.files.letter,
    ]);
    for (const sel of ["#job_application_latitude", "#resume_text", "#cover_letter_text", "#submit_app"]) {
      expect(seen.has($(sel))).toBe(false);
    }
    expect(map.files.cv).toBe($("#resume"));
    expect(map.files.letter).toBe($("#cover_letter"));
  });

  test("never clicks anything", async () => {
    await fill(map, kit, deps());
    expect(clicks).not.toHaveBeenCalled();
  });
});

describe("new form", () => {
  let map: PageMap;
  beforeEach(() => {
    document.body.innerHTML = fixture("greenhouse-new.html");
    map = greenhouse.map(document);
  });

  test("fill puts the kit into the expected ids", async () => {
    await fill(map, kit, deps());
    expect(val("#first_name")).toBe("Ana");
    expect(val("#last_name")).toBe("Exemplo");
    expect(val("#email")).toBe("ana.exemplo@example.com");
    expect(val("#question_19385420004")).toBe("https://github.com/ana-exemplo");
    expect(val("#question_19385421004")).toBe("https://ana.example.com");
    expect((($("#resume") as HTMLInputElement).files?.length)).toBe(1);
  });

  test("the location combobox maps to the city field and waits for a picker", async () => {
    const summary = await fill(map, kit, deps());
    expect(map.fields.find((f) => f.key === "basics.city")?.el).toBe($("#candidate-location"));
    expect(val("#candidate-location")).toBe("");
    const item = summary.needsYou.find((n) => n.el === $("#candidate-location"));
    expect(item?.note).toBe("pick from the list by hand");
  });

  test("LinkedIn is placed when the kit has one", async () => {
    await fill(map, kit, deps());
    expect(val("#question_19385418004")).toBe("https://linkedin.com/in/ana-exemplo");
  });

  test("phone is not filled and the country dropdown maps to the country field", async () => {
    const summary = await fill(map, kit, deps());
    expect(val("#phone")).toBe("");
    expect(map.phone).toEqual([$("#phone")]);
    const country = map.fields.find((f) => f.key === "basics.country");
    expect(country?.el).toBe($("#country"));
    expect(country?.pick?.value?.("BR")).toBe("Brazil");
    expect(map.fields.find((f) => f.key === "basics.city")?.pick?.prefix).toBe(true);
    expect(summary.needsYou.map((n) => n.el)).toContain($("#phone"));
  });

  test("EEO and demographic comboboxes are unplaced, never filled", async () => {
    const summary = await fill(map, kit, deps());
    for (const id of ["4015790004", "4015786004", "4015785004", "4015783004", "4015781004", "4015780004"]) {
      const el = $(`[id="${id}"]`);
      expect(map.unplaced).toContain(el);
      expect(val(`[id="${id}"]`)).toBe("");
      expect(summary.needsYou.map((n) => n.el)).toContain(el);
    }
  });

  test("the privacy acknowledgement goes to consent, other dropdown questions to questions", () => {
    expect(map.consent).toEqual([$("#question_19385423004")]);
    const asked = map.questions.map((q) => q.el);
    for (const id of ["question_19385414004", "question_19385415004", "question_19385417004", "question_19385424004"]) {
      expect(asked).toContain($(`#${id}`));
      expect(map.unplaced).not.toContain($(`#${id}`));
    }
  });

  test("Twitter stays unplaced and the aria-hidden required inputs are ignored", () => {
    expect(map.unplaced).toContain($("#question_19385419004"));
    const all = [...map.unplaced, ...map.consent, ...map.phone, ...map.fields.map((f) => f.el as Element)];
    expect(all.some((e) => e.getAttribute("aria-hidden") === "true")).toBe(false);
  });

  test("never clicks anything", async () => {
    await fill(map, kit, deps());
    expect(clicks).not.toHaveBeenCalled();
  });
});

describe("link questions", () => {
  test("a question that merely mentions LinkedIn or a website is a question, not the URL field", () => {
    document.body.innerHTML = `<form id="application_form">
      <label for="question_1">Did you find this role on LinkedIn?</label><input id="question_1" type="text">
      <label for="question_2">Is your personal website up to date with your recent projects?</label><input id="question_2" type="text">
      <label for="question_3">LinkedIn Profile URL</label><input id="question_3" type="text"></form>`;
    const map = greenhouse.map(document);
    expect(map.fields.map((f) => [f.key, (f.el as HTMLElement).id])).toEqual([["basics.linkedin", "question_3"]]);
    expect(map.questions.map((q) => (q.el as HTMLElement).id)).toEqual(["question_1", "question_2"]);
  });
});

describe("location", () => {
  test("city and location match as words, so ethnicity does not", () => {
    document.body.innerHTML = `<form id="application_form"><label for="ethnicity">Ethnicity</label>
      <input id="ethnicity" name="job_application[ethnicity]" type="text">
      <label for="home_city">Home</label><input id="home_city" type="text"></form>`;
    const map = greenhouse.map(document);
    expect(map.fields.map((f) => [f.key, (f.el as HTMLElement).id])).toEqual([["basics.city", "home_city"]]);
    expect(map.unplaced).toContain($("#ethnicity"));
  });

  test("a searchable combobox is a city field, a question or unplaced, whatever its role attribute", () => {
    document.body.innerHTML = `<form id="application_form">
      <label for="first_name">First name</label><input id="first_name" type="text" aria-autocomplete="both">
      <label for="loc">Location</label><input id="job_application_location" name="job_application[location]" type="text" aria-haspopup="listbox">
      <label for="question_1">Why us?</label><input id="question_1" type="text" aria-autocomplete="list"></form>`;
    const map = greenhouse.map(document);
    expect(map.fields.map((f) => [f.key, (f.el as HTMLElement).id])).toEqual([["basics.city", "job_application_location"]]);
    expect(map.questions.map((q) => (q.el as HTMLElement).id)).toEqual(["question_1"]);
    expect(map.unplaced).toContain($("#first_name"));
  });

  test("a location field whose id and name say neither city nor location is unplaced", () => {
    document.body.innerHTML = `<form id="application_form"><label for="where">Where are you?</label>
      <input id="where" name="job_application[x]" type="text"></form>`;
    const map = greenhouse.map(document);
    expect(map.fields).toEqual([]);
    expect(map.unplaced).toContain($("#where"));
  });
});

describe("adapterFor", () => {
  test("picks greenhouse on the boards hosts when the form is there", () => {
    document.body.innerHTML = fixture("greenhouse-new.html");
    expect(adapterFor(url("https://job-boards.greenhouse.io/examplecorp/jobs/4012345"), document)?.name).toBe("greenhouse");
    document.body.innerHTML = fixture("greenhouse-classic.html");
    expect(adapterFor(url("https://boards.greenhouse.io/embed/job_app?for=examplecorp&token=4012345"), document)?.name).toBe("greenhouse");
  });

  test("picks greenhouse on a gh_jid page with an embedded form", () => {
    document.body.innerHTML = fixture("greenhouse-classic.html");
    expect(adapterFor(url("https://careers.example.com/open-roles?gh_jid=4012345"), document)?.name).toBe("greenhouse");
  });

  test("declines a gh_jid page without a form, a form on an unrelated page, and lookalike hosts", () => {
    document.body.innerHTML = "<p>Open roles</p>";
    expect(adapterFor(url("https://careers.example.com/open-roles?gh_jid=4012345"), document)).toBeNull();
    document.body.innerHTML = fixture("greenhouse-classic.html");
    expect(adapterFor(url("https://careers.example.com/apply"), document)).toBeNull();
    expect(adapterFor(url("https://boards.greenhouse.io.evil.example.com/x/jobs/1"), document)).toBeNull();
  });

  test("never claims a LinkedIn page", () => {
    document.body.innerHTML = fixture("greenhouse-classic.html");
    expect(adapterFor(url("https://www.linkedin.com/jobs/view/1?gh_jid=4012345"), document)).toBeNull();
  });

  test("exposes the confirmation selector", () => {
    expect(greenhouse.confirmation).toBe('#application_confirmation, [data-testid*="confirmation"]');
  });
});
