import { describe, expect, it, vi } from "vitest";
import {
  containerAufrufenOderAusweichen, mitKaltstartWiederholung, mitSicherheitsheadern, pauseSeite, pausiert,
  workerGeheimnisPasst,
} from "./sicherheit";

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

describe("Kaltstart des Containers", () => {
  const ohneWarten = async () => {};
  const anfrage = () => new Request("https://nestor.test/api/stufe", { method: "POST", body: JSON.stringify({ stufe: "premium" }) });

  it("wiederholt eine 500 der Container-Bibliothek mit demselben Körper, bis die App antwortet", async () => {
    const koerper: string[] = [];
    const antworten = [new Response("Failed to start container: not ready", { status: 500 }), new Response("ok")];
    const antwort = await mitKaltstartWiederholung(anfrage(), async (r) => {
      koerper.push(await r.text());
      return antworten.shift()!;
    }, ohneWarten);
    expect(antwort.status).toBe(200);
    expect(koerper).toEqual(['{"stufe":"premium"}', '{"stufe":"premium"}']);
  });

  it("reicht einen Fehler der App unverändert durch, ohne Wiederholung", async () => {
    let aufrufe = 0;
    const antwort = await mitKaltstartWiederholung(anfrage(), async () => {
      aufrufe++;
      return new Response('{"detail":"kaputt"}', { status: 500 });
    }, ohneWarten);
    expect(antwort.status).toBe(500);
    expect(aufrufe).toBe(1);
  });

  it("gibt nach drei Versuchen auf", async () => {
    let aufrufe = 0;
    const antwort = await mitKaltstartWiederholung(anfrage(), async () => {
      aufrufe++;
      return new Response("Container suddenly disconnected, try again", { status: 500 });
    }, ohneWarten);
    expect(antwort.status).toBe(500);
    expect(aufrufe).toBe(3);
  });
});

describe("Notschalter NESTOR_PAUSE (Ticket #64)", () => {
  it("ist ohne gesetzte Variable aus", () => {
    expect(pausiert({})).toBe(false);
  });

  it("schaltet nur bei genau \"1\" ein", () => {
    expect(pausiert({ NESTOR_PAUSE: "1" })).toBe(true);
    expect(pausiert({ NESTOR_PAUSE: "true" })).toBe(false);
    expect(pausiert({ NESTOR_PAUSE: "0" })).toBe(false);
    expect(pausiert({ NESTOR_PAUSE: "" })).toBe(false);
  });

  it("zeigt eine freundliche Seite statt eines rohen Fehlers", async () => {
    const antwort = pauseSeite();
    expect(antwort.status).toBe(503);
    expect(await antwort.text()).toContain("keine neuen Meetings");
  });
});
