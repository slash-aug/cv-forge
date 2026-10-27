import { expect, test } from "vitest";
import { manifestFor } from "../src/manifest";

for (const b of ["chrome", "firefox"] as const) {
  test(`${b} never runs on linkedin`, () => {
    const m = manifestFor(b) as any;
    for (const cs of m.content_scripts)
      expect(cs.exclude_matches).toEqual(
        expect.arrayContaining(["*://linkedin.com/*", "*://*.linkedin.com/*"]),
      );
    expect(JSON.stringify(m.host_permissions)).not.toMatch(/linkedin|<all_urls>/);
  });
}

test("shared MV3 shape", () => {
  for (const b of ["chrome", "firefox"] as const) {
    const m = manifestFor(b) as any;
    expect(m.manifest_version).toBe(3);
    expect(m.permissions).toEqual(["storage", "tabs"]);
    expect(m.host_permissions).toEqual(["http://127.0.0.1/*"]);
    expect(m.action.default_popup).toBe("popup.html");
    expect(m.content_scripts[0]).toMatchObject({
      matches: ["https://*/*"],
      js: ["content.js"],
      all_frames: true,
      run_at: "document_idle",
    });
  }
});

test("browser specific background", () => {
  const c = manifestFor("chrome") as any;
  const f = manifestFor("firefox") as any;
  expect(c.background).toEqual({ service_worker: "background.js" });
  expect(c.browser_specific_settings).toBeUndefined();
  expect(f.background).toEqual({ scripts: ["background.js"] });
  expect(f.browser_specific_settings.gecko.id).toBe("cv-forge@local");
});
