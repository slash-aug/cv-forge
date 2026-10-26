import { KitShapeError, KitVersionError, parseKit, type Kit } from "../shared/kit";
import type { ApiError, BankEntry, Job, Result } from "../shared/messages";

const fail = (error: ApiError): Result<never> => ({ ok: false, error });

/** A server that accepts the connection but never answers counts as down. */
export const REQUEST_TIMEOUT_MS = 15_000;

export class Api {
  constructor(
    private readonly fetchFn: typeof fetch,
    private readonly getToken: () => Promise<string | null>,
    private readonly port = 47321,
  ) {}

  /** One place for the token header and the down / token / http mapping. */
  private async request(path: string, init: RequestInit = {}): Promise<Result<Response>> {
    const token = await this.getToken();
    if (!token) return fail({ kind: "token" });
    let res: Response;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Raced as well as aborted, so a fetch that ignores the signal still times out.
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        abort.abort();
        reject(new Error("timeout"));
      }, REQUEST_TIMEOUT_MS);
    });
    try {
      res = await Promise.race([
        this.fetchFn(`http://127.0.0.1:${this.port}${path}`, {
          ...init,
          signal: abort.signal,
          headers: { ...(init.headers as Record<string, string> | undefined), "X-CVForge-Token": token },
        }),
        timeout,
      ]);
    } catch {
      return fail({ kind: "down" });
    } finally {
      clearTimeout(timer);
    }
    if (res.ok) return { ok: true, value: res };
    if (res.status === 401) return fail({ kind: "token" });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    const code = typeof body === "object" && body !== null ? (body as { error?: unknown }).error : undefined;
    if (res.status === 403 && code === "linkedin") return fail({ kind: "linkedin" });
    return fail({ kind: "http", status: res.status, body });
  }

  private async getJson<T>(path: string, init?: RequestInit): Promise<Result<T>> {
    const r = await this.request(path, init);
    if (!r.ok) return r;
    try {
      return { ok: true, value: (await r.value.json()) as T };
    } catch {
      return fail({ kind: "http", status: r.value.status, body: null });
    }
  }

  health() {
    return this.getJson<{ version: number; cvforge: string }>("/health");
  }

  async jobs(): Promise<Result<Job[]>> {
    const r = await this.getJson<unknown>("/jobs");
    if (!r.ok) return r;
    const isJob = (j: unknown) =>
      typeof j === "object" && j !== null &&
      ["slug", "company", "role"].every((k) => typeof (j as Record<string, unknown>)[k] === "string");
    if (!Array.isArray(r.value) || !r.value.every(isJob)) return fail({ kind: "http", status: 200, body: null });
    return { ok: true, value: r.value as Job[] };
  }

  async match(url: string, site?: string, jobId?: string): Promise<Result<string[]>> {
    const q = new URLSearchParams({ url });
    if (site) q.set("site", site);
    if (jobId) q.set("job_id", jobId);
    const r = await this.getJson<{ slugs?: unknown } | null>(`/match?${q}`);
    if (!r.ok) return r;
    const slugs = r.value?.slugs;
    if (!Array.isArray(slugs) || !slugs.every((x) => typeof x === "string")) return fail({ kind: "http", status: 200, body: null });
    return { ok: true, value: slugs as string[] };
  }

  async kit(slug: string): Promise<Result<Kit>> {
    const r = await this.getJson<unknown>(`/kit/${encodeURIComponent(slug)}`);
    if (!r.ok) return r;
    try {
      return { ok: true, value: parseKit(r.value, slug) };
    } catch (e) {
      if (e instanceof KitVersionError || e instanceof KitShapeError) return fail({ kind: "kit", message: e.message });
      throw e;
    }
  }

  /** Fetches the kit first: its links.cv_pdf / links.letter_pdf basename is the file name and the URL segment. */
  async pdf(slug: string, which: "cv" | "letter"): Promise<Result<{ name: string; bytes: ArrayBuffer }>> {
    const kit = await this.kit(slug);
    if (!kit.ok) return kit;
    const name = which === "cv" ? kit.value.links.cv_pdf : kit.value.links.letter_pdf;
    if (!name) return fail({ kind: "http", status: 404, body: { error: "no-pdf" } });
    const r = await this.request(`/kit/${encodeURIComponent(slug)}/${which === "cv" ? "cv.pdf" : "letter.pdf"}`);
    if (!r.ok) return r;
    return { ok: true, value: { name: name.split("/").pop() ?? name, bytes: await r.value.arrayBuffer() } };
  }

  async bank(q: string, lang: string): Promise<Result<BankEntry | null>> {
    const r = await this.getJson<{ entry: BankEntry | null }>(`/bank?${new URLSearchParams({ q, lang })}`);
    return r.ok ? { ok: true, value: r.value.entry } : r;
  }

  saveAnswer(slug: string, question: string, answer: string) {
    return this.getJson<{ saved: true }>(`/answers/${encodeURIComponent(slug)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer }),
    });
  }

  markApplied(slug: string) {
    return this.getJson<{ status: string }>(`/applied/${encodeURIComponent(slug)}`, { method: "POST" });
  }
}
