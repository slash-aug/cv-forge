import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { start } from "../src/content/main";
import type { Msg, Result } from "../src/shared/messages";
import { errorText } from "../src/shared/messages";

const fixture = (name: string): string => readFileSync(resolve(__dirname, "fixtures", name), "utf8");
const kit = JSON.parse(fixture("kit.json"));
const job = { slug: kit.slug, company: "Example Corp", role: "Full-stack Engineer", posting_url: null, apply_url: null };

// The UI uses a closed shadow root; tests reach it through this spy.
const roots: ShadowRoot[] = [];
const realAttach = Element.prototype.attachShadow;
let attach: ReturnType<typeof vi.spyOn>;

const uiHost = (): Element | null => document.querySelector("[data-cvforge-ui]");
const ui = (): ShadowRoot => roots[roots.length - 1];
const text = (): string => ui().textContent ?? "";
const buttons = (): HTMLButtonElement[] => [...ui().querySelectorAll("button")];
const button = (re: RegExp): HTMLButtonElement | undefined => buttons().find((b) => re.test(b.textContent ?? ""));
const flush = async (): Promise<void> => {
  for (let i = 0; i < 500; i++) await Promise.resolve();
};

type Handler = (m: Msg) => Result<unknown>;
function makeSend(over: Partial<Record<Msg["type"], Handler>> = {}) {
  const base: Record<string, Handler> = {
    matchTab: () => ({ ok: true, value: { slug: kit.slug, candidates: [job] } }),
    kit: () => ({ ok: true, value: kit }),
    bank: () => ({ ok: true, value: null }),
    pdf: () => ({ ok: true, value: { name: "cv.pdf", base64: btoa("%PDF-1.4") } }),
    saveAnswer: () => ({ ok: true, value: { saved: true } }),
    markApplied: () => ({ ok: true, value: { status: "applied" } }),
  };
  const handlers = { ...base, ...over } as Record<string, Handler>;
  return vi.fn(async (m: Msg) => handlers[m.type](m) as Result<any>);
}
const sent = (send: ReturnType<typeof makeSend>, type: string): Msg[] =>
  send.mock.calls.map((c) => c[0]).filter((m) => m.type === type);

beforeEach(() => {
  roots.length = 0;
  attach = vi.spyOn(Element.prototype, "attachShadow").mockImplementation(function (this: Element, init: ShadowRootInit) {
    const root = realAttach.call(this, { ...init, mode: "open" });
    roots.push(root);
    return root;
  });
  uiHost()?.remove();
  sessionStorage.clear();
  document.body.innerHTML = fixture("guess-en.html");
  document.querySelector("html")?.setAttribute("style", "");
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  uiHost()?.remove();
});

describe("detection", () => {
  test("does nothing on linkedin host", async () => {
    const send = makeSend();
    const win = { document, location: new URL("https://www.linkedin.com/jobs/1") } as unknown as Window;
    await start(win, send);
    expect(send).not.toHaveBeenCalled();
    expect(uiHost()).toBeNull();
  });

  test("non-application page: no button", async () => {
    document.body.innerHTML = fixture("not-a-form.html");
    const send = makeSend();
    await start(window, send);
    expect(send).not.toHaveBeenCalled();
    expect(uiHost()).toBeNull();
  });

  test("the host is marked and appended to the root element", async () => {
    await start(window, makeSend());
    expect(uiHost()?.parentElement).toBe(document.documentElement);
  });
});

describe("button", () => {
  test("names the matched job", async () => {
    const send = makeSend();
    await start(window, send);
    expect(buttons()[0].textContent).toBe("Fill for Example Corp, Full-stack Engineer");
    expect(buttons()[0].disabled).toBe(false);
    expect(sent(send, "matchTab")[0]).toMatchObject({ type: "matchTab", url: window.location.href });
  });

  test("no matched job: choose in the popup; a click picks up the popup choice", async () => {
    let slug: string | null = null;
    const send = makeSend({ matchTab: () => ({ ok: true, value: { slug, candidates: [job] } }) });
    await start(window, send);
    expect(buttons()[0].textContent).toBe("Choose job in the cv-forge popup");
    expect(buttons()[0].disabled).toBe(false);
    slug = kit.slug;
    buttons()[0].click();
    await flush();
    expect(buttons()[0].textContent).toBe("Fill for Example Corp, Full-stack Engineer");
    expect(sent(send, "kit")).toHaveLength(0);
  });

  test("window focus while no job is chosen re-asks", async () => {
    let slug: string | null = null;
    const send = makeSend({ matchTab: () => ({ ok: true, value: { slug, candidates: [job] } }) });
    await start(window, send);
    slug = kit.slug;
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(buttons()[0].textContent).toBe("Fill for Example Corp, Full-stack Engineer");
  });

  test("visibilitychange while no job is chosen re-asks; once chosen it does not", async () => {
    let slug: string | null = null;
    const send = makeSend({ matchTab: () => ({ ok: true, value: { slug, candidates: [job] } }) });
    await start(window, send);
    slug = kit.slug;
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();
    const n = sent(send, "matchTab").length;
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(sent(send, "matchTab").length).toBe(n);
  });

  test("a stale matchTab response is ignored", async () => {
    let release: (v: Result<any>) => void = () => {};
    let calls = 0;
    const send = vi.fn(async (m: Msg): Promise<Result<any>> => {
      if (m.type !== "matchTab") return { ok: true, value: null };
      calls++;
      if (calls === 1) return new Promise((r) => (release = r));
      return { ok: true, value: { slug: kit.slug, candidates: [job] } };
    });
    void start(window, send);
    await flush();
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(buttons()[0].textContent).toBe("Fill for Example Corp, Full-stack Engineer");
    release({ ok: true, value: { slug: null, candidates: [] } });
    await flush();
    expect(buttons()[0].textContent).toBe("Fill for Example Corp, Full-stack Engineer");
  });

  test("the UI host resists page CSS", async () => {
    await start(window, makeSend());
    const host = uiHost() as HTMLElement;
    expect(host.style.getPropertyPriority("display")).toBe("important");
    expect(host.style.display).toBe("block");
  });

  test("a rejecting send shows the internal error instead of throwing", async () => {
    const send = vi.fn(async () => {
      throw new Error("Extension context invalidated.");
    });
    await start(window, send as any);
    expect(buttons()[0].textContent).toBe(errorText({ kind: "internal" }));
  });

  test("an undefined response is the internal error", async () => {
    await start(window, (async () => undefined) as any);
    expect(buttons()[0].textContent).toBe(errorText({ kind: "internal" }));
  });

  test("server down: button shows the start command", async () => {
    const send = makeSend({ matchTab: () => ({ ok: false, error: { kind: "down" } }) });
    await start(window, send);
    expect(buttons()[0].textContent).toBe(errorText({ kind: "down" }));
    expect(buttons()[0].textContent).toContain("cvforge serve");
  });

  test("no fill until click", async () => {
    const send = makeSend();
    await start(window, send);
    await flush();
    expect((document.getElementById("fn") as HTMLInputElement).value).toBe("");
    expect(sent(send, "kit")).toHaveLength(0);
    buttons()[0].click();
    await flush();
    expect((document.getElementById("fn") as HTMLInputElement).value).toBe("Ana");
    expect(sent(send, "kit")).toHaveLength(1);
  });

  test("kit error shows its text on the button", async () => {
    const send = makeSend({ kit: () => ({ ok: false, error: { kind: "kit", message: "Rerun cvforge kit x" } }) });
    await start(window, send);
    buttons()[0].click();
    await flush();
    expect(buttons()[0].textContent).toBe("Rerun cvforge kit x");
  });

  test("the pdf is fetched by message and attached", async () => {
    const send = makeSend();
    await start(window, send);
    buttons()[0].click();
    await flush();
    expect(sent(send, "pdf")[0]).toEqual({ type: "pdf", slug: kit.slug, which: "cv" });
    const input = document.getElementById("cvf") as HTMLInputElement;
    expect(input.files?.[0].name).toBe("cv.pdf");
  });
});

describe("summary", () => {
  test("groups and scroll on click, never a page click", async () => {
    const clicks = vi.spyOn(HTMLElement.prototype, "click");
    await start(window, makeSend());
    const fillClick = buttons()[0];
    fillClick.click();
    await flush();
    clicks.mockClear();
    for (const g of ["Filled", "Guessed", "Attached", "Suggested", "Needs you"]) expect(text()).toContain(g);
    const phone = button(/phone/i) as HTMLButtonElement;
    expect(phone).toBeTruthy();
    phone.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "center" });
    expect(document.activeElement).toBe(document.getElementById("ph"));
    expect(clicks).not.toHaveBeenCalled();
  });
});

describe("answers", () => {
  const fillPage = async (send: ReturnType<typeof makeSend>) => {
    await start(window, send);
    buttons()[0].click();
    await flush();
  };
  const why = () => document.getElementById("why") as HTMLTextAreaElement;
  const typeAndBlur = (v: string) => {
    why().value = v;
    why().dispatchEvent(new Event("blur"));
  };

  test("save offer posts on click only", async () => {
    const send = makeSend();
    await fillPage(send);
    expect(button(/save answer/i)).toBeUndefined();
    typeAndBlur("Because of the team.");
    expect(sent(send, "saveAnswer")).toHaveLength(0);
    button(/save answer/i)?.click();
    await flush();
    expect(sent(send, "saveAnswer")[0]).toEqual({
      type: "saveAnswer", slug: kit.slug, question: "Why Example Corp?", answer: "Because of the team.",
    });
    expect(text()).toContain("Saved");
  });

  test("no offer when the field is still empty", async () => {
    await fillPage(makeSend());
    typeAndBlur("  ");
    expect(button(/save answer/i)).toBeUndefined();
  });

  test("audit failure shows each finding inline and nothing else", async () => {
    const body = {
      error: "audit-secret-code",
      findings: [
        { kind: "number", ref: "7", message: "7 is not in master" },
        { kind: "term", ref: "x", message: "Mentions a confidential term" },
      ],
    };
    const send = makeSend({ saveAnswer: () => ({ ok: false, error: { kind: "http", status: 422, body } }) });
    await fillPage(send);
    typeAndBlur("I led 7 teams.");
    button(/save answer/i)?.click();
    await flush();
    expect(text()).toContain("7 is not in master");
    expect(text()).toContain("Mentions a confidential term");
    expect(text()).not.toContain("audit-secret-code");
    expect(text()).not.toContain("Saved");
  });

  test("a rejecting saveAnswer re-enables Save and shows the error", async () => {
    const send = makeSend({ saveAnswer: () => { throw new Error("Receiving end does not exist"); } });
    await fillPage(send);
    typeAndBlur("Because.");
    const save = button(/save answer/i) as HTMLButtonElement;
    save.click();
    await flush();
    expect(save.disabled).toBe(false);
    expect(text()).toContain(errorText({ kind: "internal" }));
  });

  test("one offer per field: a second blur replaces the chip", async () => {
    await fillPage(makeSend());
    typeAndBlur("One.");
    typeAndBlur("Two.");
    expect(ui().querySelectorAll(".chip")).toHaveLength(1);
  });

  test("after Saved the offer goes away and does not come back", async () => {
    vi.useFakeTimers();
    const send = makeSend();
    await fillPage(send);
    typeAndBlur("Because.");
    button(/save answer/i)?.click();
    await flush();
    expect(text()).toContain("Saved");
    await vi.advanceTimersByTimeAsync(2500);
    expect(ui().querySelectorAll(".chip")).toHaveLength(0);
    typeAndBlur("Because again.");
    expect(button(/save answer/i)).toBeUndefined();
  });

  test("a second fill saves under the new closure, with one offer", async () => {
    const send = makeSend();
    await fillPage(send);
    buttons()[0].click();
    await flush();
    typeAndBlur("Again.");
    expect(ui().querySelectorAll(".chip")).toHaveLength(1);
    button(/save answer/i)?.click();
    await flush();
    expect(sent(send, "saveAnswer")).toHaveLength(1);
  });

  test("use saved answer: typing removes the chip", async () => {
    const send = makeSend({ bank: () => ({ ok: true, value: { question: "q", answer: "Great mission." } }) });
    await fillPage(send);
    why().dispatchEvent(new Event("input", { bubbles: true }));
    expect(button(/use saved answer/i)).toBeUndefined();
  });

  test("use saved answer does not overwrite a field that is no longer empty", async () => {
    const send = makeSend({ bank: () => ({ ok: true, value: { question: "q", answer: "Great mission." } }) });
    await fillPage(send);
    const use = button(/use saved answer/i) as HTMLButtonElement;
    why().value = "typed by hand";
    use.click();
    await flush();
    expect(why().value).toBe("typed by hand");
  });

  test("use saved answer fills only after click", async () => {
    const send = makeSend({ bank: () => ({ ok: true, value: { question: "Why us?", answer: "Great mission." } }) });
    await fillPage(send);
    expect(sent(send, "bank")[0]).toMatchObject({ type: "bank", lang: "en" });
    expect(why().value).toBe("");
    button(/use saved answer/i)?.click();
    await flush();
    expect(why().value).toBe("Great mission.");
  });
});

describe("mark applied", () => {
  const thankYou = async (send: ReturnType<typeof makeSend>, submit: boolean) => {
    vi.useFakeTimers();
    await start(window, send);
    if (submit) document.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    document.body.innerHTML = "<p>Thank you for applying!</p>";
    await vi.advanceTimersByTimeAsync(600);
    await flush();
  };

  test("thank-you page after submit offers mark applied; sends nothing without a click", async () => {
    const send = makeSend();
    await thankYou(send, true);
    const mark = button(/mark as applied/i);
    expect(mark).toBeTruthy();
    expect(sent(send, "markApplied")).toHaveLength(0);
    mark?.click();
    await flush();
    expect(sent(send, "markApplied")).toEqual([{ type: "markApplied", slug: kit.slug }]);
  });

  test("a rejecting markApplied re-enables the button and shows the error", async () => {
    const send = makeSend({ markApplied: () => { throw new Error("gone"); } });
    await thankYou(send, true);
    const mark = button(/mark as applied/i) as HTMLButtonElement;
    mark.click();
    await flush();
    expect(mark.disabled).toBe(false);
    expect(text()).toContain(errorText({ kind: "internal" }));
  });

  test("the submitted mark is cleared once the prompt is offered", async () => {
    await thankYou(makeSend(), true);
    expect(sessionStorage.getItem("cvforge:submitted")).toBeNull();
  });

  test("greenhouse: the confirmation page has no form but still offers it", async () => {
    document.body.innerHTML = `<form id="application_form">
      <label for="a">First name</label><input id="a" name="job_application[first_name]">
      <label for="b">Last name</label><input id="b" name="job_application[last_name]">
      <label for="c">Email</label><input id="c" name="job_application[email]"></form>`;
    const win = {
      document,
      location: new URL("https://job-boards.greenhouse.io/examplecorp/jobs/4012345"),
      addEventListener: window.addEventListener.bind(window),
      removeEventListener: window.removeEventListener.bind(window),
    } as unknown as Window;
    vi.useFakeTimers();
    const send = makeSend();
    await start(win, send);
    expect(sent(send, "matchTab")[0]).toMatchObject({ site: "greenhouse", jobId: "4012345" });
    document.getElementById("application_form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    document.body.innerHTML = '<div id="application_confirmation">Done</div>';
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    const mark = button(/mark as applied/i);
    expect(mark).toBeTruthy();
    expect(sent(send, "markApplied")).toHaveLength(0);
    mark?.click();
    await flush();
    expect(sent(send, "markApplied")).toHaveLength(1);
  });

  test("thank-you text without a prior submit on that host offers nothing", async () => {
    const send = makeSend();
    await thankYou(send, false);
    expect(button(/mark as applied/i)).toBeUndefined();
    expect(sent(send, "markApplied")).toHaveLength(0);
  });

  test("a fresh load of the thank-you page after a submit offers it", async () => {
    sessionStorage.setItem("cvforge:submitted", window.location.hostname);
    document.body.innerHTML = "<p>Your application has been received.</p>";
    const send = makeSend();
    await start(window, send);
    expect(button(/mark as applied/i)).toBeTruthy();
    expect(sent(send, "markApplied")).toHaveLength(0);
  });
});

describe("multi-step", () => {
  const addStep = (id: string) =>
    document.body.insertAdjacentHTML("beforeend", `<label for="${id}">Last name</label><input id="${id}" name="${id}">`);

  test("a new step re-offers the button without filling", async () => {
    vi.useFakeTimers();
    const send = makeSend();
    await start(window, send);
    buttons()[0].click();
    await flush();
    const before = sent(send, "matchTab").length;
    addStep("x2");
    await vi.advanceTimersByTimeAsync(600);
    await flush();
    expect(sent(send, "matchTab").length).toBe(before + 1);
    expect(buttons()[0].textContent).toBe("Fill for Example Corp, Full-stack Engineer");
    expect((document.getElementById("x2") as HTMLInputElement).value).toBe("");
    expect(sent(send, "kit")).toHaveLength(1);
  });

  test("a steady stream of mutations still rechecks within 2 s", async () => {
    vi.useFakeTimers();
    const send = makeSend();
    await start(window, send);
    const before = sent(send, "matchTab").length;
    for (let i = 0; i < 6; i++) {
      addStep(`s${i}`);
      await vi.advanceTimersByTimeAsync(400);
    }
    await flush();
    expect(sent(send, "matchTab").length).toBeGreaterThan(before);
  });

  test("after a fill, highlight attribute changes and UI changes do not re-ask", async () => {
    vi.useFakeTimers();
    const send = makeSend();
    await start(window, send);
    buttons()[0].click();
    await flush();
    await vi.advanceTimersByTimeAsync(1000);
    const before = sent(send, "matchTab").length;
    document.getElementById("fn")?.setAttribute("data-cvforge-reason", "x");
    (document.getElementById("fn") as HTMLElement).style.outline = "1px solid red";
    ui().appendChild(document.createElement("div"));
    buttons()[0].click();
    await flush();
    await vi.advanceTimersByTimeAsync(3000);
    await flush();
    expect(sent(send, "matchTab").length).toBe(before);
  });
});
