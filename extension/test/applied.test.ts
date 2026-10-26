import { beforeEach, describe, expect, test } from "vitest";
import { clearSubmitted, detectSent, rememberAdapter, rememberedAdapterName, watchSubmit } from "../src/content/applied";
import type { Adapter } from "../src/adapters/types";

const loc = (url: string): URL => new URL(url);
const adapter = { name: "x", confirmation: "#done" } as unknown as Adapter;

beforeEach(() => {
  sessionStorage.clear();
  document.body.innerHTML = "<form><input></form>";
});

const formEl = (): HTMLFormElement => document.querySelector("form") as HTMLFormElement;

describe("watchSubmit", () => {
  test("records the host on submit and never prevents or triggers anything", () => {
    watchSubmit(formEl(), "jobs.example.com");
    const ev = new Event("submit", { bubbles: true, cancelable: true });
    formEl().dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    expect(sessionStorage.getItem("cvforge:submitted")).toBe("jobs.example.com");
  });

  test("nothing is recorded without a submit", () => {
    watchSubmit(formEl(), "jobs.example.com");
    expect(sessionStorage.getItem("cvforge:submitted")).toBeNull();
  });

  test("a submit of some other form is not recorded", () => {
    document.body.insertAdjacentHTML("beforeend", "<form id='other'></form>");
    watchSubmit(formEl(), "jobs.example.com");
    document.getElementById("other")?.dispatchEvent(new Event("submit", { bubbles: true }));
    expect(sessionStorage.getItem("cvforge:submitted")).toBeNull();
  });

  test("clearSubmitted removes the mark", () => {
    sessionStorage.setItem("cvforge:submitted", "jobs.example.com");
    clearSubmitted();
    expect(sessionStorage.getItem("cvforge:submitted")).toBeNull();
  });
});

describe("remembered adapter", () => {
  test("is kept per host", () => {
    rememberAdapter("jobs.example.com", "greenhouse");
    expect(rememberedAdapterName("jobs.example.com")).toBe("greenhouse");
    expect(rememberedAdapterName("other.example.com")).toBeNull();
  });
});

describe("detectSent", () => {
  test("adapter confirmation selector matches", () => {
    document.body.innerHTML = '<div id="done"></div>';
    expect(detectSent(document, loc("https://jobs.example.com/x"), adapter)).toBe(true);
  });

  test("thank-you text with the flag for the same host", () => {
    sessionStorage.setItem("cvforge:submitted", "jobs.example.com");
    document.body.innerHTML = "<p>Thank you for applying!</p>";
    expect(detectSent(document, loc("https://jobs.example.com/done"), null)).toBe(true);
  });

  test.each([
    "Your application has been received",
    "Candidatura enviada com sucesso",
    "Obrigada por se candidatar",
  ])("matches %s", (text) => {
    sessionStorage.setItem("cvforge:submitted", "jobs.example.com");
    document.body.textContent = text;
    expect(detectSent(document, loc("https://jobs.example.com/"), null)).toBe(true);
  });

  test("text without the flag is not enough", () => {
    document.body.innerHTML = "<p>Thank you for applying!</p>";
    expect(detectSent(document, loc("https://jobs.example.com/"), null)).toBe(false);
  });

  test("flag for another host is not enough", () => {
    sessionStorage.setItem("cvforge:submitted", "other.example.com");
    document.body.innerHTML = "<p>Thank you for applying!</p>";
    expect(detectSent(document, loc("https://jobs.example.com/"), null)).toBe(false);
  });

  test("flag without matching text is false", () => {
    sessionStorage.setItem("cvforge:submitted", "jobs.example.com");
    document.body.innerHTML = "<p>Fill in your details</p>";
    expect(detectSent(document, loc("https://jobs.example.com/"), null)).toBe(false);
  });
});
