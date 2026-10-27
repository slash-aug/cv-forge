import { build } from "esbuild";
import { copyFile, mkdir, rm, writeFile } from "node:fs/promises";
import { manifestFor } from "./src/manifest.ts";

const entries = {
  background: "src/background/main.ts",
  content: "src/content/main.ts",
  popup: "src/popup/popup.ts",
};

for (const browser of ["chrome", "firefox"]) {
  const out = `dist/${browser}`;
  await rm(out, { recursive: true, force: true });
  await mkdir(out, { recursive: true });
  await build({
    entryPoints: Object.fromEntries(Object.entries(entries).map(([k, v]) => [k, v])),
    outdir: out,
    bundle: true,
    format: "iife",
    target: "es2022",
    logLevel: "warning",
  });
  await copyFile("src/popup/popup.html", `${out}/popup.html`);
  await writeFile(`${out}/manifest.json`, JSON.stringify(manifestFor(browser), null, 2) + "\n");
}
