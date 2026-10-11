// Datenspende gestreamt je Datei (Ticket #82): PUT /intern/spende/<name>/<datei> streamt request.body direkt
// in R2.put (kein formData()/arrayBuffer() mehr, das im Isolate puffert/kopiert und bei einer 45-MB-Aufnahme auf
// 90–135 MB kam) und POST .../abschluss markiert vollständig/teilweise. Dieselbe Härtung wie zuvor (Ticket #63):
// Pfad/Dateiname eng begrenzt, Größenobergrenze, gleiche Worker-Geheimnis-Prüfung.
import { describe, expect, it, vi } from "vitest";

vi.mock("cloudflare:workers", () => ({ DurableObject: class {} }));
vi.mock("@cloudflare/containers", () => ({
  Container: class { constructor(_ctx: unknown, _env: unknown) {} },
  getContainer: () => ({ fetch: async () => new Response("nicht genutzt") }),
}));

const { default: worker } = await import("./index");

const abgelegt: { key: string; groesse: number; contentType?: string }[] = [];

function neuerEnv(ueberschreibungen: Record<string, unknown> = {}) {
  abgelegt.length = 0;
  return {
    WORKER_GEHEIMNIS: "worker-geheim",
    COOKIE_GEHEIMNIS: "cookie-geheim",
    SPENDEN: {
      put: async (key: string, value: ReadableStream | null, options?: { httpMetadata?: { contentType?: string } }) => {
        let groesse = 0;
        if (value) {
          const reader = value.getReader();
          for (;;) {
            const { done, value: chunk } = await reader.read();
            if (done) break;
            groesse += chunk.byteLength;
          }
        }
        abgelegt.push({ key, groesse, contentType: options?.httpMetadata?.contentType });
      },
    },
    ...ueberschreibungen,
  } as unknown as Parameters<typeof worker.fetch>[1];
}

const ctx = { waitUntil: (p: Promise<unknown>) => p, passThroughOnException: () => {} } as unknown as ExecutionContext;

function koerperAnfrage(pfad: string, methode: string, body: string, kopf: Record<string, string> = {}) {
  return new Request(`https://nestor.test${pfad}`, {
    method: methode, body,
    headers: { "X-Nestor-Geheimnis": "worker-geheim", "Content-Length": String(body.length), ...kopf },
  });
}

describe("PUT /intern/spende/<name>/<datei> (Ticket #82)", () => {
  it("streamt den Körper direkt in R2.put, ohne formData()/arrayBuffer()", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(koerperAnfrage("/intern/spende/abc12345/transkript.md", "PUT", "**[00:00] A:** Hallo\n"), env, ctx);
    expect(antwort.status).toBe(200);
    expect(await antwort.json()).toEqual({ ok: true, bytes: "**[00:00] A:** Hallo\n".length });
    expect(abgelegt).toEqual([{ key: "abc12345/transkript.md", groesse: "**[00:00] A:** Hallo\n".length, contentType: "application/octet-stream" }]);
  });

  it("verlangt das Worker-Geheimnis wie der alte Weg", async () => {
    const env = neuerEnv();
    const anfrage = new Request("https://nestor.test/intern/spende/abc12345/transkript.md", {
      method: "PUT", body: "x", headers: { "Content-Length": "1" },
    });
    const antwort = await worker.fetch(anfrage, env, ctx);
    expect(antwort.status).toBe(403);
    expect(abgelegt).toHaveLength(0);
  });

  it("weist einen Pfadausbruch über '..' im Dateinamen ab", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(koerperAnfrage("/intern/spende/abc12345/..%2f..%2fetc%2fpasswd", "PUT", "x"), env, ctx);
    expect(antwort.status).toBe(400);
    expect(abgelegt).toHaveLength(0);
  });

  it("weist einen nicht erlaubten Dateinamen ab (nur die bekannten Endungen)", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(koerperAnfrage("/intern/spende/abc12345/schadcode.exe", "PUT", "x"), env, ctx);
    expect(antwort.status).toBe(400);
    expect(abgelegt).toHaveLength(0);
  });

  it("weist eine ungültige Spende-ID ab (nicht die erwarteten Hex-Zeichen von _kurz_id())", async () => {
    // Ein wörtliches ".." in der URL löst bereits die URL-Klasse selbst auf (auch percent-codiert, WHATWG-URL-
    // Spezifikation) – ein Pfadausbruch über den ID-Teil ist so gar nicht erst konstruierbar. Das Muster fängt
    // stattdessen jede andere unerwartete ID ab, z. B. hier Großbuchstaben.
    const env = neuerEnv();
    const antwort = await worker.fetch(koerperAnfrage("/intern/spende/ABCDEFGH/transkript.md", "PUT", "x"), env, ctx);
    expect(antwort.status).toBe(400);
    expect(abgelegt).toHaveLength(0);
  });

  it("lässt künftige Textdateien wie nestor.jsonl (#83) ohne Änderung am Muster durch", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(koerperAnfrage("/intern/spende/abc12345/nestor.jsonl", "PUT", '{"a":1}\n'), env, ctx);
    expect(antwort.status).toBe(200);
  });

  it("verlangt Content-Length und weist eine Datei über der Obergrenze ab", async () => {
    const env = neuerEnv();
    const ohneLaenge = new Request("https://nestor.test/intern/spende/abc12345/transkript.md", {
      method: "PUT", body: "x", headers: { "X-Nestor-Geheimnis": "worker-geheim" },
    });
    expect((await worker.fetch(ohneLaenge, env, ctx)).status).toBe(411);

    const zuGross = new Request("https://nestor.test/intern/spende/abc12345/aufnahme.wav", {
      method: "PUT", body: "x",
      headers: { "X-Nestor-Geheimnis": "worker-geheim", "Content-Length": String(301 * 1024 * 1024) },
    });
    expect((await worker.fetch(zuGross, env, ctx)).status).toBe(413);
    expect(abgelegt).toHaveLength(0);
  });

  it("nur PUT ist erlaubt", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(koerperAnfrage("/intern/spende/abc12345/transkript.md", "POST", "x"), env, ctx);
    expect(antwort.status).toBe(405);
  });
});

describe("POST /intern/spende/<name>/abschluss (Ticket #82)", () => {
  const abschlussAnfrage = (name: string, koerper: unknown) =>
    new Request(`https://nestor.test/intern/spende/${name}/abschluss`, {
      method: "POST", body: JSON.stringify(koerper),
      headers: { "X-Nestor-Geheimnis": "worker-geheim", "Content-Type": "application/json" },
    });

  it("meldet 'vollstaendig', wenn jede Datei ok war", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(abschlussAnfrage("abc12345", {
      ergebnisse: [{ datei: "transkript.md", bytes: 120, ok: true }, { datei: "aufnahme.wav", bytes: 45_000_000, ok: true }],
      dauerMs: 4200,
    }), env, ctx);
    expect(antwort.status).toBe(200);
    expect(await antwort.json()).toEqual({ ok: true, vollstaendig: true });
  });

  it("meldet 'teilweise', wenn nur die Aufnahme scheiterte – die Texte zählen trotzdem", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(abschlussAnfrage("abc12345", {
      ergebnisse: [
        { datei: "transkript.md", bytes: 120, ok: true },
        { datei: "feedback.txt", bytes: 10, ok: true },
        { datei: "aufnahme.wav", bytes: 45_000_000, ok: false },
      ],
      dauerMs: 31_000,
    }), env, ctx);
    expect(antwort.status).toBe(200);
    expect(await antwort.json()).toEqual({ ok: true, vollstaendig: false });
  });

  it("meldet 'fehlgeschlagen' ohne jede Datei – und verlangt das Worker-Geheimnis", async () => {
    const env = neuerEnv();
    const antwort = await worker.fetch(abschlussAnfrage("abc12345", { ergebnisse: [], dauerMs: 100 }), env, ctx);
    expect((await antwort.json())).toEqual({ ok: true, vollstaendig: false });

    const ohneGeheimnis = new Request("https://nestor.test/intern/spende/abc12345/abschluss", {
      method: "POST", body: JSON.stringify({ ergebnisse: [] }),
    });
    expect((await worker.fetch(ohneGeheimnis, env, ctx)).status).toBe(403);
  });
});
