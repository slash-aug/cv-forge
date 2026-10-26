export interface KitLinks {
  apply: string | null;
  posting: string | null;
  cv_pdf: string | null;
  letter_pdf: string | null;
}

export interface KitField {
  key: string;
  label: string;
  value: string;
  group: "personal" | "links" | "preferences";
}

export interface KitWork {
  key: string;
  title: string;
  company: string;
  start: string;
  end: string | null;
  description: { "200": string; "500": string; "1000": string; "2000": string };
}

export interface KitEducation {
  key: string;
  dates: string;
  degree: string;
  institution: string;
}

export interface KitLanguage {
  key: string;
  name: string;
  detail: string;
}

export interface KitCertificate {
  key: string;
  date: string;
  name: string;
  issuer: string;
}

export interface KitSalary {
  confirmed: boolean;
  text: string;
  sources: string[];
  amount: number | null;
  currency: string | null;
  period: "year" | "month" | "hour" | null;
}

export interface KitAnswer {
  question: string;
  answer: string;
  limit: number | null;
}

/** Typed so real kits parse. The extension never fills or sends the email. */
export interface KitEmail {
  to: string;
  subject: string;
  body: string;
  attachments: string[];
}

export interface Kit {
  schema_version: 2;
  slug: string;
  lang: "en" | "pt-BR" | "pt-PT";
  company: string;
  role: string;
  links: KitLinks;
  fields: KitField[];
  work: KitWork[];
  education: KitEducation[];
  languages: KitLanguage[];
  certificates: KitCertificate[];
  salary: KitSalary | null;
  answers: KitAnswer[];
  recruiter_note: { connect: string; message: string } | null;
  email: KitEmail | null;
  tracker: string[];
}

export class KitVersionError extends Error {
  constructor(message = "Kit is from an older cv-forge. Rerun: cvforge kit <slug>") {
    super(message);
    this.name = "KitVersionError";
  }
}

export class KitShapeError extends Error {
  constructor(message = "Kit is malformed. Rerun: cvforge kit <slug>") {
    super(message);
    this.name = "KitShapeError";
  }
}

const ARRAY_KEYS = ["fields", "work", "education", "languages", "certificates", "answers", "tracker"];
const OBJECT_OR_NULL_KEYS = ["salary", "recruiter_note", "email"];

const isObject = (v: unknown): boolean => typeof v === "object" && v !== null && !Array.isArray(v);

export function parseKit(raw: unknown): Kit {
  const version = typeof raw === "object" && raw !== null ? (raw as { schema_version?: unknown }).schema_version : undefined;
  if (version !== 2) throw new KitVersionError();
  const kit = raw as Record<string, unknown>;
  for (const key of ARRAY_KEYS) if (!Array.isArray(kit[key])) throw new KitShapeError();
  for (const key of OBJECT_OR_NULL_KEYS) if (kit[key] !== null && !isObject(kit[key])) throw new KitShapeError();
  if (!isObject(kit.links)) throw new KitShapeError();
  return raw as Kit;
}
