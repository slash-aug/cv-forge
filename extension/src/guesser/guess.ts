import { isConsent } from "../content/consent";
import { labelText } from "../content/dom";
import type { Control, FieldKey, FieldSlot, PageMap, QuestionSlot, SalarySlot, Target } from "../fill/pagemap";
import { normaliseQuestion } from "../shared/normalise";

type Key = FieldKey | "phone" | "salary";

// Raw keywords, EN and PT. Normalised once at load, so stopwords drop on both sides.
const RAW: Record<Key, string[]> = {
  "basics.first_name": ["first name", "firstname", "given name", "forename", "primeiro nome"],
  "basics.last_name": ["last name", "lastname", "surname", "family name", "sobrenome", "ultimo nome"],
  "basics.name": ["name", "full name", "nome", "nome completo"],
  "basics.email": ["email", "e-mail", "email address", "endereco de email"],
  "basics.city": ["city", "town", "cidade", "municipio"],
  "basics.region": ["state", "province", "region", "estado", "provincia", "regiao"],
  "basics.country": ["country", "pais"],
  "basics.linkedin": ["linkedin"],
  "basics.github": ["github"],
  "basics.portfolio": ["portfolio", "website", "web site", "personal website", "personal site", "homepage", "site"],
  "prefs.visa": ["visa", "visto", "work authorization", "work authorisation", "sponsorship", "autorizacao de trabalho"],
  "prefs.notice": ["notice period", "notice", "aviso previo"],
  "prefs.relocation": ["relocation", "relocate", "realocacao", "relocacao"],
  phone: ["phone", "phone number", "telephone", "tel", "mobile", "telefone", "celular", "whatsapp"],
  salary: [
    "salary", "salary expectation", "desired salary", "salario", "pretensao salarial",
    "expectativa salarial", "remuneracao", "expected compensation", "compensation",
  ],
};

const KEYWORDS = Object.entries(RAW).map(([key, words]) => ({
  key: key as Key,
  words: words.map((w) => normaliseQuestion(w).split(" ")).filter((t) => t[0] !== ""),
}));

const AUTOCOMPLETE: Record<string, Key> = {
  "given-name": "basics.first_name",
  "family-name": "basics.last_name",
  name: "basics.name",
  email: "basics.email",
  "address-level2": "basics.city",
  "address-level1": "basics.region",
  country: "basics.country",
  "country-name": "basics.country",
  url: "basics.portfolio",
};

const CV_HINT = /\b(cv|resume|curriculo|curriculum)\b/;
const LETTER_HINT = /\b(cover|carta|motivation|motivacao)\b/;
// A generic keyword ("name", "site") does not count next to one of these.
const MODIFIERS = new Set(
  ["company", "employer", "empresa", "reference", "referencia", "school", "escola", "university",
   "universidade", "manager", "gestor", "contact", "contato", "emergency", "emergencia"].map((w) => normaliseQuestion(w)),
);
const GENERIC_KEYS = new Set<Key>(["basics.name", "basics.portfolio", "prefs.notice", "basics.region"]);
const TEXT_TYPES = new Set(["", "text", "email", "tel", "url", "search", "number"]);
const SKIP_TYPES = new Set(["search", "hidden", "submit", "button", "reset", "image"]);
const MAX_SIGNAL_TOKENS = 6;
const HINT_LIMIT = 200;

const fold = (t: string): string => t.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
const squash = (t: string): string => t.replace(/\s+/g, " ").trim();

function visible(el: Element): boolean {
  if (el instanceof HTMLInputElement && el.type === "hidden") return false;
  if (el.matches(":disabled") || el.closest("[inert], [role=search]")) return false;
  if (el.getAttribute("autocomplete") === "one-time-code") return false;
  if (el.checkVisibility?.() === false) return false;
  for (let n: Element | null = el; n; n = n.parentElement) {
    if (n instanceof HTMLDetailsElement && !n.open) {
      const summary = [...n.children].find((c) => c.localName === "summary");
      if (!summary?.contains(el)) return false;
    }
    if (n.hasAttribute("hidden") || n.getAttribute("aria-hidden") === "true") return false;
    if (n instanceof HTMLElement && (n.style.display === "none" || n.style.visibility === "hidden")) return false;
  }
  return true;
}

function contains(tokens: string[], phrase: string[]): boolean {
  for (let i = 0; i + phrase.length <= tokens.length; i++) {
    if (phrase.every((p, j) => tokens[i + j] === p)) return true;
  }
  return false;
}

/** Score each key from a set of signal texts; ties and zero scores yield null. */
function rank(signals: string[], el?: Control, autocomplete = ""): { key: Key | null; tie: boolean } {
  const scores = new Map<Key, number>();
  const add = (key: Key, n: number): void => void scores.set(key, (scores.get(key) ?? 0) + n);
  for (const raw of signals) {
    const tokens = normaliseQuestion(raw).split(" ").filter(Boolean);
    if (tokens.length === 0 || tokens.length > MAX_SIGNAL_TOKENS) continue;
    for (const { key, words } of KEYWORDS) {
      let best = 0;
      const modified = tokens.some((t) => MODIFIERS.has(t));
      for (const w of words) {
        if (!contains(tokens, w)) continue;
        if (modified && w.length === 1 && GENERIC_KEYS.has(key)) continue;
        best = Math.max(best, w.length * 2 + (w.length === tokens.length ? 2 : 0));
      }
      if (best) add(key, best);
    }
  }
  for (const token of autocomplete.toLowerCase().split(/\s+/)) {
    if (token.startsWith("tel")) add("phone", 10);
    else if (AUTOCOMPLETE[token]) add(AUTOCOMPLETE[token], 10);
  }
  if (el instanceof HTMLInputElement) {
    if (el.type === "email") add("basics.email", 3);
    if (el.type === "tel") add("phone", 3);
  }
  const ranked = [...scores].sort((a, b) => b[1] - a[1]);
  const top = ranked[0];
  if (!top) return { key: null, tie: false };
  if (ranked[1]?.[1] === top[1]) return { key: null, tie: true };
  return { key: top[0], tie: false };
}

const bestKey = (signals: string[], el?: Control, autocomplete = ""): Key | null =>
  rank(signals, el, autocomplete).key;

function signalsOf(el: Control): string[] {
  const attr = [el.getAttribute("name") ?? "", el.id].map((s) => s.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " "));
  return [labelText(el), el.getAttribute("placeholder") ?? "", ...attr];
}

const legendOf = (el: Element): string => squash(el.closest("fieldset")?.querySelector("legend")?.textContent ?? "");

/** Label text plus the closest legend or parent text, for currency and period hints. */
function hintText(el: Control): string {
  const near = legendOf(el) || squash(el.parentElement?.textContent ?? "");
  return fold(`${labelText(el)} ${near}`).slice(0, HINT_LIMIT);
}

function currencyOf(hint: string): string | null {
  if (/r\$|\bbrl\b/.test(hint)) return "BRL";
  if (/€|\beur\b/.test(hint)) return "EUR";
  if (/\busd\b|\$/.test(hint)) return "USD";
  return null;
}

function periodOf(hint: string): SalarySlot["period"] {
  const found = [
    /per year|\/ ?year|annual|yearly|anual|por ano/.test(hint) ? "year" : null,
    /per month|\/ ?month|monthly|mensal|por mes/.test(hint) ? "month" : null,
    /per hour|\/ ?hour|hourly|por hora/.test(hint) ? "hour" : null,
  ].filter((p): p is "year" | "month" | "hour" => p !== null);
  return found.length === 1 ? (found[0] ?? null) : null;
}

const LIMIT_TEXT =
  /[([]?\s*(?:max(?:imum)?|up to|at[eé]|m[aá]ximo)?\s*(\d{2,6})\s*(?:characters|chars|caracteres)\s*(?:max(?:imum)?)?\s*[)\]]?/i;

function limitOf(el: Control, label: string): { maxLength: number | null; label: string } {
  const attr = el.getAttribute("maxlength");
  const m = LIMIT_TEXT.exec(label);
  const cleaned = m ? squash(label.replace(m[0], " ")) : label;
  const n = attr !== null ? Number(attr) : m ? Number(m[1]) : NaN;
  return { maxLength: n > 0 ? n : null, label: cleaned };
}

function fileKind(el: HTMLInputElement): "cv" | "letter" | null {
  const text = fold(`${labelText(el)} ${el.name} ${el.id} ${el.accept}`);
  if (LETTER_HINT.test(text)) return "letter";
  return CV_HINT.test(text) ? "cv" : null;
}

function consentPhrase(doc: Document, text: string): boolean {
  const probe = doc.createElement("input");
  probe.type = "checkbox";
  probe.setAttribute("aria-label", text);
  return isConsent(probe);
}

function isRelevant(el: Element): el is Control {
  if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement)) {
    return false;
  }
  if (el instanceof HTMLInputElement && SKIP_TYPES.has(el.type)) return false;
  if (el.disabled) return false;
  if (!(el instanceof HTMLSelectElement) && el.readOnly) return false;
  return visible(el);
}

export function looksLikeApplication(doc: Document): boolean {
  const controls = [...doc.querySelectorAll("input, textarea, select")].filter(isRelevant);
  let email = false;
  let name = false;
  for (const el of controls) {
    if (el instanceof HTMLInputElement && el.type === "file") {
      if (CV_HINT.test(fold(`${labelText(el)} ${el.name} ${el.accept}`))) return true;
      continue;
    }
    const key = bestKey(signalsOf(el), el, el.autocomplete);
    if (key === "basics.email") email = true;
    if (key === "basics.name" || key === "basics.first_name" || key === "basics.last_name") name = true;
  }
  return email && name;
}

export function guessPage(doc: Document): PageMap {
  const map: PageMap = {
    source: "guesser", fields: [], questions: [], files: {}, salary: null,
    phone: [], consent: [], unplaced: [], lists: [], allowClicks: [],
  };
  const seenRadio = new Set<string>();
  const fieldAt = (key: FieldKey): FieldSlot | undefined => map.fields.find((f) => f.key === key);

  const place = (key: Key | null, el: Target, control: Control): boolean => {
    if (key === null) return false;
    if (key === "phone") {
      map.phone.push(control);
      return true;
    }
    if (key === "salary") {
      if (map.salary || Array.isArray(el)) return false;
      const hint = hintText(control);
      map.salary = { el: control, currency: currencyOf(hint), period: periodOf(hint) };
      return true;
    }
    if (fieldAt(key)) return false;
    map.fields.push({ key, el, guessed: true });
    return true;
  };

  const question = (label: string, el: Target, control: Control): boolean => {
    if (!label) return false;
    const { maxLength, label: clean } = limitOf(control, label);
    const q: QuestionSlot = { label: clean, el, maxLength };
    map.questions.push(q);
    return true;
  };

  for (const el of doc.querySelectorAll("input, textarea, select")) {
    if (!isRelevant(el)) continue;

    if (el instanceof HTMLInputElement && el.type === "file") {
      const kind = fileKind(el);
      if (kind && !map.files[kind]) map.files[kind] = el;
      else map.unplaced.push(el);
      continue;
    }

    if (el instanceof HTMLInputElement && el.type === "checkbox") {
      const legend = legendOf(el);
      if (isConsent(el) || (legend && consentPhrase(doc, legend))) map.consent.push(el);
      else map.unplaced.push(el);
      continue;
    }

    if (el instanceof HTMLInputElement && el.type === "radio") {
      const id = `${el.form ? [...doc.forms].indexOf(el.form) : -1}:${el.name}`;
      if (el.name && seenRadio.has(id)) continue;
      seenRadio.add(id);
      const group = (el.name
        ? [...doc.querySelectorAll<HTMLInputElement>("input[type=radio]")].filter(
            (r) => r.name === el.name && r.form === el.form,
          )
        : [el]
      ).filter(isRelevant) as HTMLInputElement[];
      const legend = legendOf(el);
      const signals = [legend, el.name.replace(/[_-]+/g, " ")];
      if (!place(bestKey(signals), group, el) && !question(legend, group, el)) map.unplaced.push(el);
      continue;
    }

    if (el instanceof HTMLInputElement && !TEXT_TYPES.has(el.type)) continue;

    const isArea = el instanceof HTMLTextAreaElement;
    const { key, tie } = isArea ? { key: null, tie: false } : rank(signalsOf(el), el, el.autocomplete);
    if (place(key, el, el)) continue;
    if (key === null && !(el instanceof HTMLSelectElement)) {
      const label = squash(labelText(el) || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "");
      // A text input whose keywords tied is ambiguous; a textarea is always a question.
      if (!tie && question(label, el, el)) continue;
    }
    map.unplaced.push(el);
  }

  // A bare "Name" next to a last-name field is the first name.
  const bare = fieldAt("basics.name");
  if (bare && fieldAt("basics.last_name") && !fieldAt("basics.first_name")) bare.key = "basics.first_name";

  return map;
}
