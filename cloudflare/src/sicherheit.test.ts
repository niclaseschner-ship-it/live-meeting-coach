import { describe, expect, it, vi } from "vitest";
import { containerAufrufenOderAusweichen, mitSicherheitsheadern, workerGeheimnisPasst } from "./sicherheit";

describe("Worker-Geheimnis für /intern/*", () => {
  it("lässt die richtige Kopfzeile durch", () => {
    const anfrage = new Request("https://x/intern/interessenten", { headers: { "X-Nestor-Geheimnis": "geheim" } });
    expect(workerGeheimnisPasst(anfrage, "geheim")).toBe(true);
  });

  it("weist falsche, fehlende oder leere Geheimnisse ab", () => {
    const ohne = new Request("https://x/intern/interessenten");
    expect(workerGeheimnisPasst(ohne, "geheim")).toBe(false);
    const falsch = new Request("https://x/intern/interessenten", { headers: { "X-Nestor-Geheimnis": "falsch" } });
    expect(workerGeheimnisPasst(falsch, "geheim")).toBe(false);
    expect(workerGeheimnisPasst(falsch, "")).toBe(false);
  });
});

describe("Sicherheitsheader", () => {
  it("setzt CSP, X-Frame-Options, Referrer-Policy und nosniff, ohne den Rumpf zu verändern", async () => {
    const roh = new Response("hallo", { status: 200, headers: { "content-type": "text/plain" } });
    const geschuetzt = mitSicherheitsheadern(roh);
    expect(await geschuetzt.text()).toBe("hallo");
    expect(geschuetzt.headers.get("content-type")).toBe("text/plain");
    expect(geschuetzt.headers.get("X-Frame-Options")).toBe("DENY");
    expect(geschuetzt.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(geschuetzt.headers.get("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    const csp = geschuetzt.headers.get("Content-Security-Policy") ?? "";
    const richtlinien = new Map(csp.split("; ").map((teil) => {
      const [name, ...werte] = teil.split(" ");
      return [name, werte];
    }));
    expect(richtlinien.get("default-src")).toEqual(["'self'"]);
    expect(richtlinien.get("frame-ancestors")).toEqual(["'none'"]);
    // nur style-src bekommt die 'unsafe-inline'-Ausnahme (Worker-eigene <style>-Blöcke), nicht script-src
    // blob: nur, weil Chrome audioWorklet.addModule(blob:…) gegen script-src prüft (basis.js, agenda.js) –
    // ohne diese Ausnahme wären Mikrofon und Agenda-Mikro tot; 'unsafe-inline' bleibt draußen
    expect(richtlinien.get("script-src")).toEqual(["'self'", "blob:"]);
    expect(richtlinien.get("style-src")).toEqual(["'self'", "'unsafe-inline'"]);
    expect(richtlinien.get("worklet-src")).toEqual(["'self'", "blob:"]);
  });
});

describe("Kapazitätsfehler", () => {
  it("gibt die normale Antwort durch, wenn der Aufruf gelingt", async () => {
    const melden = vi.fn();
    const antwort = await containerAufrufenOderAusweichen(async () => new Response("ok"), melden, "test");
    expect(await antwort.text()).toBe("ok");
    expect(melden).not.toHaveBeenCalled();
  });

  it("fängt einen Fehler ab, meldet ihn und zeigt die freundliche Seite", async () => {
    const melden = vi.fn();
    const antwort = await containerAufrufenOderAusweichen(
      async () => { throw new Error("Kaltstart-Timeout"); }, melden, "startseite",
    );
    expect(antwort.status).toBe(503);
    expect(await antwort.text()).toContain("Gerade ausgelastet");
    expect(melden).toHaveBeenCalledTimes(1);
    expect(melden.mock.calls[0][0]).toContain("Kaltstart-Timeout");
  });
  it("reicht WebSocket-Upgrades unverändert durch (sonst gehen Audio- und Handy-Kanal verloren)", () => {
    const upgrade = { status: 101, webSocket: {}, headers: new Headers() } as unknown as Response;
    expect(mitSicherheitsheadern(upgrade)).toBe(upgrade);
  });
});
