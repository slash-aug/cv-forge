import { expect, test } from "vitest";
import { isLinkedInHost } from "../src/shared/linkedin";

test("linkedin hosts", () => {
  for (const h of ["linkedin.com", "www.linkedin.com", "LINKEDIN.COM.", "br.linkedin.com"])
    expect(isLinkedInHost(h), h).toBe(true);
});

test("other hosts", () => {
  for (const h of ["notlinkedin.com", "linkedin.com.evil.io", "example.com", ""])
    expect(isLinkedInHost(h), h).toBe(false);
});
