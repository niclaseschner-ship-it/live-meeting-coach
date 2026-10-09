import { describe, it, expect } from "vitest";
import { mitVariantenwahl, type Variantenwahl } from "./variantenwahl";

function speicher(initial?: Variantenwahl) {
  let value = initial;
  return { get: async <T>() => value as T | undefined,
    put: async (_key: string, v: Variantenwahl) => { value = v; }, lesen: () => value };
}
const req = (path = "/meeting", method = "GET") => new Request(`https://pilot.test${path}`, {
  method, headers: { "X-Nestor-Stufe": "premium", "X-Nestor-Modus": "live" },
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
      async () => Response.json({ ok: true, stufe: "premium", modus: "live" }));
    await mitVariantenwahl(req(), store, async r => {
      expect(r.headers.get("X-Nestor-Stufe")).toBe("premium");
      expect(r.headers.get("X-Nestor-Modus")).toBe("live");
      return new Response("ok");
    });
  });
  it("409 oder Fehler überschreiben keine vorher bestätigte Wahl", async () => {
    const store = speicher({ stufe: "premium", modus: "live" });
    for (const status of [409, 503]) {
      await mitVariantenwahl(req("/api/stufe", "POST"), store, async () => new Response("Fehler", { status }));
      expect(store.lesen()?.stufe).toBe("premium");
    }
  });
  it("ungültige Erfolgsantwort wird sichtbar abgewiesen", async () => {
    const store = speicher();
    const r = await mitVariantenwahl(req("/api/stufe", "POST"), store,
      async () => Response.json({ ok: true, stufe: "premium", modus: "knopfdruck" }));
    expect(r.status).toBe(502);
    expect(store.lesen()).toBeUndefined();
  });
});
