import { describe, it, expect } from "vitest";
import { meetingBeenden, mitVariantenwahl, varianteText, type Variantenwahl } from "./variantenwahl";

function speicher(initial?: Variantenwahl) {
  const werte = new Map<string, Variantenwahl | boolean>(initial ? [["variantenwahl", initial]] : []);
  return { get: async <T>(key: string) => werte.get(key) as T | undefined,
    put: async (key: string, v: Variantenwahl | boolean) => { werte.set(key, v); },
    lesen: () => werte.get("variantenwahl") as Variantenwahl | undefined };
}
const req = (path = "/meeting", method = "GET") => new Request(`https://pilot.test${path}`, {
  method, headers: { "X-Nestor-Stufe": "premium" },
});
describe("Bestätigte Variantenwahl", () => {
  it("übernimmt keine beliebigen Browser-Header", async () => {
    await mitVariantenwahl(req(), speicher(), async r => {
      expect(r.headers.has("X-Nestor-Stufe")).toBe(false);
      return new Response("ok");
    });
  });
  it("bewahrt erfolgreiche Premium-Auswahl für neue Container-Anfragen", async () => {
    const store = speicher();
    await mitVariantenwahl(req("/api/stufe", "POST"), store,
      async () => Response.json({ ok: true, stufe: "premium" }));
    await mitVariantenwahl(req(), store, async r => {
      expect(r.headers.get("X-Nestor-Stufe")).toBe("premium");
      return new Response("ok");
    });
  });
  it("409 oder Fehler überschreiben keine vorher bestätigte Wahl", async () => {
    const store = speicher({ stufe: "premium" });
    for (const status of [409, 503]) {
      await mitVariantenwahl(req("/api/stufe", "POST"), store, async () => new Response("Fehler", { status }));
      expect(store.lesen()?.stufe).toBe("premium");
    }
  });
  it("ungültige Erfolgsantwort wird sichtbar abgewiesen", async () => {
    const store = speicher();
    const r = await mitVariantenwahl(req("/api/stufe", "POST"), store,
      async () => Response.json({ ok: true, stufe: "gold" }));
    expect(r.status).toBe(502);
    expect(store.lesen()).toBeUndefined();
  });
});

describe("Ticket #60: keine Vorgabe-Stufe, beendete Meetings", () => {
  it("ohne gespeicherte Wahl geht keine Stufe an den Container (er bleibt unbestimmt)", async () => {
    await mitVariantenwahl(req(), speicher(), async r => {
      expect(r.headers.has("X-Nestor-Stufe")).toBe(false);
      return new Response("ok");
    });
  });
  it("nach „Fertig“ erreicht kein Aufruf mehr den Container – 410 und Cookie gelöscht", async () => {
    const store = speicher({ stufe: "premium" });
    await meetingBeenden(store);
    let erreicht = false;
    const r = await mitVariantenwahl(req("/handy"), store, async () => { erreicht = true; return new Response("ok"); });
    expect(r.status).toBe(410);
    expect(erreicht).toBe(false);
    expect(r.headers.get("Set-Cookie")).toContain("nestor_meeting=; Max-Age=0");
  });
  it("die Startmeldung nennt die Variante", () => {
    expect(varianteText("premium")).toBe("Premium (OpenAI)");
    expect(varianteText("basis")).toBe("Basis (Mistral)");
    expect(varianteText(undefined)).toBe("unbekannt");
  });
});
