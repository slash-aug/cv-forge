import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, test } from "vitest";

const SRC = resolve(__dirname, "../src");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return sources(path);
    return /\.(ts|html|css)$/.test(e.name) ? [path] : [];
  });
}

const read = (rel: string): string => readFileSync(join(SRC, rel), "utf8");

/** [r, g, b] in 0..255 for #rgb, #rrggbb, rgb() or the keyword white; null for anything else. */
function rgb(colour: string): [number, number, number] | null {
  const c = colour.trim().toLowerCase();
  if (c === "white") return [255, 255, 255];
  const fn = /^rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(c);
  if (fn) return [Number(fn[1]), Number(fn[2]), Number(fn[3])];
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(c)?.[1];
  if (!hex) return null;
  const full = hex.length === 3 ? [...hex].map((x) => x + x).join("") : hex;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as [number, number, number];
}

/** WCAG relative luminance, 0 black to 1 white. */
function luminance(colour: string): number {
  const [r, g, b] = (rgb(colour) ?? [0, 0, 0]).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const contrast = (a: string, b: string): number => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

/** Every literal colour given to a background or a background token, inline styles included. */
const BACKGROUND = /(?:background(?:-color)?|--bg[\w-]*)["']?\s*[:=]\s*["']?(#[0-9a-f]{3,6}\b|white\b|rgba?\([^)]*\))/gi;

const token = (css: string, name: string): string => new RegExp(`${name}\\s*:\\s*(#[0-9a-f]{3,6})`, "i").exec(css)?.[1] ?? "";

describe("dark UI", () => {
  test("no source file gives anything a light background", () => {
    const light = sources(SRC).flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(BACKGROUND)]
        .map((m) => m[1] as string)
        .filter((c) => luminance(c) >= 0.1)
        .map((c) => `${file.slice(SRC.length + 1)}: ${c}`),
    );
    expect(light).toEqual([]);
  });

  test.each([
    ["on-page UI", "content/ui.ts"],
    ["popup", "popup/popup.html"],
  ])("the %s asks for dark controls and keeps text readable", (_name, file) => {
    const css = read(file);
    expect(css).toMatch(/color-scheme:\s*dark/);
    expect(contrast(token(css, "--fg"), token(css, "--bg"))).toBeGreaterThanOrEqual(4.5);
  });
});
