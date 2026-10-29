import { isConsent, isConsentText } from "../content/consent";
import { countryName } from "../content/combobox";
import { isCombobox, labelText, legendText } from "../content/dom";
import type { Control, FieldKey, FieldSlot, PageMap, Target } from "../fill/pagemap";
import { isLinkedInHost } from "../shared/linkedin";
import { normaliseQuestion } from "../shared/normalise";
import type { Adapter } from "./types";

const HOSTS = new Set(["boards.greenhouse.io", "job-boards.greenhouse.io"]);
// Classic boards use #application_form, the newer React boards #application-form.
const FORM = "#application_form, #application-form";
// The new boards keep EEO and demographic questions in this container; the classic ones in these.
const SENSITIVE = "#eeoc_fields, #demographic_questions, #demographic-section, .demographic--container";
const SENSITIVE_NAME = /^job_application\[(gender|race|hispanic_ethnicity|veteran_status|disability_status)\]/;
const DIGITS = /^[0-9]+$/;
// Location fields, recognised by id or name words.
const CITY = /\b(city|location)\b/;
const idWords = (el: Control): string => `${el.id} ${el.name}`.toLowerCase().replace(/[_\-[\]]+/g, " ");

const squash = (t: string): string => t.replace(/\s+/g, " ").trim();
const cleanLabel = (t: string): string => squash(t).replace(/\s*\*$/, "");
const fold = (t: string): string => t.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();

function digits(value: string | null): string | null {
  return value !== null && DIGITS.test(value) ? value : null;
}

const hostOf = (loc: URL): string => loc.hostname.toLowerCase().replace(/\.+$/, "");

function jobId(loc: URL): string | null {
  if (isLinkedInHost(loc.hostname)) return null;
  if (HOSTS.has(hostOf(loc))) {
    const found = /^\/[^/]+\/jobs\/([^/]+)\/?$/.exec(loc.pathname);
    if (found && digits(found[1] ?? null)) return found[1] ?? null;
    if (loc.pathname.replace(/\/+$/, "") === "/embed/job_app" && digits(loc.searchParams.get("token"))) {
      return loc.searchParams.get("token");
    }
  }
  return digits(loc.searchParams.get("gh_jid"));
}

function claims(loc: URL, doc: Document): boolean {
  if (isLinkedInHost(loc.hostname)) return false;
  const ours = HOSTS.has(hostOf(loc)) || digits(loc.searchParams.get("gh_jid")) !== null;
  return ours && doc.querySelector(FORM) !== null;
}

/** `job_application[first_name]` gives "first_name"; the new boards have no names, only ids. */
function slug(el: Control): string {
  return /^job_application\[(\w+)\]$/.exec(el.name)?.[1] ?? el.id;
}

function relevant(el: Element): el is Control {
  if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement)) {
    return false;
  }
  if (el instanceof HTMLInputElement && ["hidden", "submit", "button", "reset", "image"].includes(el.type)) return false;
  if (el.disabled || el.hasAttribute("hidden") || el.closest("[hidden]")) return false;
  if (el.getAttribute("aria-hidden") === "true") return false;
  return true;
}

const SIMPLE: Record<string, FieldKey | "phone"> = {
  first_name: "basics.first_name",
  last_name: "basics.last_name",
  email: "basics.email",
  phone: "phone",
};

const LINK_LABELS = new Set(["linkedin profile", "github", "website", "portfolio", "twitter"]);

/** Links asked as custom questions, recognised by short field labels, never by a sentence that mentions them. */
function linkKey(label: string): FieldKey | "skip" | null {
  const l = fold(label);
  if (!LINK_LABELS.has(l) && (l.includes("?") || normaliseQuestion(label).split(" ").length > 4)) return null;
  if (/linkedin/.test(l)) return "basics.linkedin";
  if (/github/.test(l)) return "basics.github";
  if (/\b(website|portfolio|personal site)\b/.test(l)) return "basics.portfolio";
  if (/twitter|\bx\b|facebook|instagram/.test(l)) return "skip";
  return null;
}

function questionLabel(el: Control): string {
  return cleanLabel(legendText(el) || labelText(el));
}

function map(doc: Document): PageMap {
  const m: PageMap = {
    source: "adapter", adapter: "greenhouse", fields: [], questions: [], files: {}, salary: null,
    phone: [], consent: [], unplaced: [], lists: [], allowClicks: [],
  };
  const root: ParentNode = doc.querySelector(FORM) ?? doc;
  const seenRadio = new Set<string>();
  const has = (key: FieldKey): boolean => m.fields.some((f) => f.key === key);
  const field = (key: FieldKey, el: Target, pick?: FieldSlot["pick"]): void => {
    if (has(key)) m.unplaced.push(Array.isArray(el) ? (el[0] as Element) : el);
    else m.fields.push({ key, el, guessed: false, ...(pick ? { pick } : {}) });
  };

  for (const el of root.querySelectorAll("input, textarea, select")) {
    if (!relevant(el)) continue;
    const id = slug(el);

    if (el.closest(SENSITIVE) || SENSITIVE_NAME.test(el.name)) {
      if (el instanceof HTMLInputElement && el.type === "radio") {
        if (seenRadio.has(el.name)) continue;
        seenRadio.add(el.name);
      }
      m.unplaced.push(el);
      continue;
    }

    if (el instanceof HTMLInputElement && el.type === "file") {
      if (id === "resume" && !m.files.cv) m.files.cv = el;
      else if (id === "cover_letter" && !m.files.letter) m.files.letter = el;
      else m.unplaced.push(el);
      continue;
    }

    // The manual-entry text boxes behind "Enter manually" are not form questions.
    if (id === "resume_text" || id === "cover_letter_text") continue;

    if (el instanceof HTMLInputElement && el.type === "checkbox") {
      (isConsent(el) || /data_compliance/.test(el.name) ? m.consent : m.unplaced).push(el);
      continue;
    }

    if (el instanceof HTMLInputElement && el.type === "radio") {
      const key = `${el.name}`;
      if (el.name && seenRadio.has(key)) continue;
      seenRadio.add(key);
      const group = (el.name
        ? [...root.querySelectorAll<HTMLInputElement>("input[type=radio]")].filter((r) => r.name === el.name)
        : [el]
      ).filter(relevant) as HTMLInputElement[];
      const label = questionLabel(el);
      if (label === "") m.unplaced.push(el);
      else if (isConsentText(label)) m.consent.push(el);
      else m.questions.push({ label, el: group, maxLength: null });
      continue;
    }

    const simple = SIMPLE[id];
    if (simple === "phone") {
      m.phone.push(el);
      continue;
    }

    // Searchable dropdowns (country, location, react-select questions): the engine picks an
    // option through deps.pick; consent stays with the user and anything else is unplaced.
    if (isCombobox(el)) {
      const label = questionLabel(el);
      const isQuestion = el.id.startsWith("question_") || el.name.includes("answers_attributes");
      if (label !== "" && isConsentText(label)) m.consent.push(el as HTMLInputElement);
      else if (id === "country") field("basics.country", el, { value: countryName });
      else if (CITY.test(idWords(el)) && !isQuestion) field("basics.city", el, { prefix: true });
      else if (isQuestion && label !== "") m.questions.push({ label, el, maxLength: null });
      else m.unplaced.push(el);
      continue;
    }
    if (simple) {
      field(simple, el);
      continue;
    }

    // Location autocomplete: the text input only, and only when its id or name says so.
    if (CITY.test(idWords(el)) && !el.id.startsWith("question_")) {
      if (has("basics.city")) m.unplaced.push(el);
      else field("basics.city", el);
      continue;
    }

    const label = questionLabel(el);
    const isQuestion = el.id.startsWith("question_") || el.name.includes("answers_attributes");
    if (!isQuestion || label === "") {
      m.unplaced.push(el);
      continue;
    }
    if (isConsentText(label)) {
      (el instanceof HTMLInputElement ? m.consent : m.unplaced).push(el);
      continue;
    }
    const link = linkKey(label);
    if (link === "skip") m.unplaced.push(el);
    else if (link) field(link, el);
    else {
      const max = Number(el.getAttribute("maxlength"));
      m.questions.push({ label, el, maxLength: max > 0 ? max : null });
    }
  }
  return m;
}

export const greenhouse: Adapter = {
  name: "greenhouse",
  claims,
  jobId: (loc) => jobId(loc),
  map,
  confirmation: '#application_confirmation, [data-testid*="confirmation"]',
};
