import type { AllowList } from "../content/clicks";

export type FieldKey =
  | "basics.name" | "basics.first_name" | "basics.last_name" | "basics.email" | "basics.city"
  | "basics.region" | "basics.country" | "basics.linkedin" | "basics.github" | "basics.portfolio"
  | "prefs.visa" | "prefs.notice" | "prefs.relocation";

export type Control = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

/** An array is a radio group. */
export type Target = Control | HTMLInputElement[];

export interface FieldSlot {
  key: FieldKey;
  el: Target;
  guessed: boolean;
  /** For a searchable dropdown: how the adapter wants the kit value picked. */
  pick?: { value?: (v: string) => string; prefix?: boolean };
}

export interface QuestionSlot {
  label: string;
  el: Target;
  maxLength: number | null;
}

export interface SummaryItem {
  label: string;
  el: Element | null;
  note?: string;
}

export interface ListSlot {
  kind: "work" | "education" | "languages" | "certificates";
  /** Entries already on the page. */
  existing(): HTMLElement[];
  /** Adapter-only selectors; the guesser leaves this undefined. */
  add?: { button: string; save?: string };
  /** Fills empty controls only. */
  fillEntry(entry: HTMLElement, item: unknown): { filled: SummaryItem[]; needsYou: SummaryItem[] };
  /** Clicks add (through safeClick) and returns the new entry. */
  openEntry?(): Promise<HTMLElement | null>;
}

export interface SalarySlot {
  el: Control;
  currency: string | null;
  period: "year" | "month" | "hour" | null;
}

export interface PageMap {
  source: "adapter" | "guesser";
  adapter?: string;
  fields: FieldSlot[];
  questions: QuestionSlot[];
  files: { cv?: HTMLInputElement; letter?: HTMLInputElement };
  salary: SalarySlot | null;
  phone: Element[];
  consent: HTMLInputElement[];
  unplaced: Element[];
  lists: ListSlot[];
  allowClicks: AllowList;
}
