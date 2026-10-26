export type Browser = "chrome" | "firefox";

export function manifestFor(browser: Browser): object {
  const base = {
    manifest_version: 3,
    name: "cv-forge",
    version: "0.1.0",
    description: "Fills job application forms from a cv-forge kit. You click submit.",
    permissions: ["storage", "tabs"],
    host_permissions: ["http://127.0.0.1/*"],
    action: { default_popup: "popup.html" },
    content_scripts: [
      {
        matches: ["https://*/*"],
        exclude_matches: ["*://linkedin.com/*", "*://*.linkedin.com/*"],
        js: ["content.js"],
        all_frames: true,
        run_at: "document_idle",
      },
    ],
  };
  if (browser === "chrome") return { ...base, background: { service_worker: "background.js" } };
  return {
    ...base,
    background: { scripts: ["background.js"] },
    browser_specific_settings: { gecko: { id: "cv-forge@local" } },
  };
}
