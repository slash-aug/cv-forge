import type { PageMap } from "../fill/pagemap";

/** A site adapter claims a site's pages and maps its form with stable ids, not guesses. */
export interface Adapter {
  name: string;
  claims(loc: URL, doc: Document): boolean;
  /** The site's id for the posting, same rules as the server's site_job_id. */
  jobId(loc: URL, doc: Document): string | null;
  map(doc: Document): PageMap;
  /** Selector that matches the site's "application submitted" page. */
  confirmation?: string;
}
