export type ApiError =
  | { kind: "down" }
  | { kind: "token" }
  | { kind: "linkedin" }
  | { kind: "kit"; message: string }
  | { kind: "internal" }
  | { kind: "http"; status: number; body: unknown };

export type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

export interface Job {
  slug: string;
  company: string;
  role: string;
  posting_url: string | null;
  apply_url: string | null;
}

export interface Match {
  slug: string | null;
  candidates: Job[];
}

export interface BankEntry {
  question: string;
  answer: string;
}

/**
 * tabId is needed for the remembered choice; content scripts get it from the sender instead.
 * chooseJob carries the tab's URL: the choice holds only on that site.
 */
export type Msg =
  | { type: "status" }
  | { type: "jobs" }
  | { type: "matchTab"; url: string; site?: string; jobId?: string; tabId?: number }
  | { type: "chooseJob"; tabId: number; slug: string; url: string }
  | { type: "kit"; slug: string }
  | { type: "pdf"; slug: string; which: "cv" | "letter" }
  | { type: "bank"; q: string; lang: string }
  | { type: "saveAnswer"; slug: string; question: string; answer: string }
  | { type: "markApplied"; slug: string }
  | { type: "setToken"; token: string };

export function errorText(e: ApiError): string {
  switch (e.kind) {
    case "down":
      return "cv-forge server not running: run .venv/bin/cvforge serve";
    case "token":
      return "Pairing token rejected: paste the token from cvforge serve --show-token";
    case "linkedin":
      return "cv-forge does not run on LinkedIn";
    case "internal":
      return "cv-forge extension error: reload the extension";
    case "kit":
      return e.message;
    case "http":
      return `Server error ${e.status}`;
  }
}
