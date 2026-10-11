// Datenspende gestreamt je Datei: PUT /intern/spende/<name>/<datei> streamt request.body direkt in R2.put, ohne
// ihn zu puffern. Eine große Datei geht stattdessen in Teilen über die Multipart-Unterbefehle (?teile=start,
// ?teil=N&upload=, ?teile=fertig). POST .../abschluss markiert vollständig/teilweise und löst die eine
// Telegram-Meldung aus. Pfad/Dateiname bleiben eng begrenzt, je Weg gilt eine eigene Größenobergrenze, dieselbe
// Worker-Geheimnis-Prüfung wie überall unter /intern/*.
import { describe, expect, it, vi } from "vitest";

vi.mock("cloudflare:workers", () => ({ DurableObject: class {} }));
vi.mock("@cloudflare/containers", () => ({
  Container: class { constructor(_ctx: unknown, _env: unknown) {} },
  getContainer: () => ({ fetch: async () => new Response("nicht genutzt") }),
}));

const { default: worker } = await import("./index");

const abgelegt: { key: string; groesse: number; contentType?: string }[] = [];
const mehrteiligeUploads = new Map<string, { key: string; teile: Map<number, Uint8Array> }>();
let uploadZaehler = 0;

async function gesamtGroesse(value: ReadableStream | null): Promise<Uint8Array> {
  if (!value) return new Uint8Array(0);
  const reader = value.getReader();
  const stuecke: Uint8Array[] = [];
  for (;;) {
    const { done, value: chunk } = await reader.read();
    if (done) break;
    stuecke.push(chunk);
  }
  const bytes = new Uint8Array(stuecke.reduce((n, s) => n + s.byteLength, 0));
  let versatz = 0;
  for (const s of stuecke) { bytes.set(s, versatz); versatz += s.byteLength; }
  return bytes;
}

function neuerEnv(ueberschreibungen: Record<string, unknown> = {}) {
  abgelegt.length = 0;
  mehrteiligeUploads.clear();
  uploadZaehler = 0;
  return {
    WORKER_GEHEIMNIS: "worker-geheim",
    COOKIE_GEHEIMNIS: "cookie-geheim",
    SPENDEN: {
      put: async (key: string, value: ReadableStream | null, options?: { httpMetadata?: { contentType?: string } }) => {
        const bytes = await gesamtGroesse(value);
        abgelegt.push({ key, groesse: bytes.byteLength, contentType: options?.httpMetadata?.contentType });
      },
      createMultipartUpload: async (key: string) => {
        const uploadId = `upload-${++uploadZaehler}`;
        mehrteiligeUploads.set(uploadId, { key, teile: new Map() });
        return { key, uploadId };
      },
      resumeMultipartUpload: (key: string, uploadId: string) => ({
        uploadPart: async (partNumber: number, value: ReadableStream | null) => {
          const eintrag = mehrteiligeUploads.get(uploadId);
          if (!eintrag) throw new Error("unbekannte uploadId");
          eintrag.teile.set(partNumber, await gesamtGroesse(value));
          return { partNumber, etag: `etag-${partNumber}` };
        },
        complete: async (teileAngaben: { partNumber: number; etag: string }[]) => {
          const eintrag = mehrteiligeUploads.get(uploadId);
          if (!eintrag) throw new Error("unbekannte uploadId");
          const groesse = teileAngaben.reduce((n, t) => n + (eintrag.teile.get(t.partNumber)?.byteLength ?? 0), 0);
          abgelegt.push({ key: eintrag.key, groesse, contentType: "application/octet-stream" });
          mehrteiligeUploads.delete(uploadId);
          return { size: groesse };
        },
      }),
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

describe("PUT /intern/spende/<name>/<datei>", () => {
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

  it("lässt künftige Textdateien mit einer bekannten Endung ohne Änderung am Muster durch", async () => {
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

describe("Multipart-Upload einer großen Datei (start/teil/fertig)", () => {
  const start = (datei: string) =>
    new Request(`https://nestor.test/intern/spende/abc12345/${datei}?teile=start`, {
      method: "POST", headers: { "X-Nestor-Geheimnis": "worker-geheim" },
    });
  const teil = (datei: string, nr: number, uploadId: string, body: string, kopf: Record<string, string> = {}) =>
    new Request(`https://nestor.test/intern/spende/abc12345/${datei}?teil=${nr}&upload=${uploadId}`, {
      method: "PUT", body,
      headers: { "X-Nestor-Geheimnis": "worker-geheim", "Content-Length": String(body.length), ...kopf },
    });
  const fertig = (datei: string, koerper: unknown) =>
    new Request(`https://nestor.test/intern/spende/abc12345/${datei}?teile=fertig`, {
      method: "POST", body: JSON.stringify(koerper),
      headers: { "X-Nestor-Geheimnis": "worker-geheim", "Content-Type": "application/json" },
    });

  it("start → zwei Teile → fertig legt die zusammengesetzte Datei in R2 ab", async () => {
    const env = neuerEnv();
    const startAntwort = await worker.fetch(start("aufnahme.wav"), env, ctx);
    expect(startAntwort.status).toBe(200);
    const { uploadId } = (await startAntwort.json()) as { uploadId: string };
    expect(uploadId).toBeTruthy();

    const teil1 = await worker.fetch(teil("aufnahme.wav", 1, uploadId, "A".repeat(10)), env, ctx);
    expect(teil1.status).toBe(200);
    expect(await teil1.json()).toEqual({ partNumber: 1, etag: "etag-1" });
    const teil2 = await worker.fetch(teil("aufnahme.wav", 2, uploadId, "B".repeat(5)), env, ctx);
    expect(await teil2.json()).toEqual({ partNumber: 2, etag: "etag-2" });

    const fertigAntwort = await worker.fetch(fertig("aufnahme.wav", {
      uploadId, teile: [{ partNumber: 1, etag: "etag-1" }, { partNumber: 2, etag: "etag-2" }],
    }), env, ctx);
    expect(fertigAntwort.status).toBe(200);
    expect(await fertigAntwort.json()).toEqual({ ok: true, bytes: 15 });
    expect(abgelegt).toEqual([{ key: "abc12345/aufnahme.wav", groesse: 15, contentType: "application/octet-stream" }]);
  });

  it("verlangt das Worker-Geheimnis auf allen drei Unterbefehlen", async () => {
    const env = neuerEnv();
    const ohneGeheimnis = (r: Request) => new Request(r, { headers: new Headers() });
    expect((await worker.fetch(ohneGeheimnis(start("aufnahme.wav")), env, ctx)).status).toBe(403);
    expect((await worker.fetch(ohneGeheimnis(teil("aufnahme.wav", 1, "irrelevant", "x")), env, ctx)).status).toBe(403);
    expect((await worker.fetch(ohneGeheimnis(fertig("aufnahme.wav", {})), env, ctx)).status).toBe(403);
  });

  it("weist eine Teilnummer außerhalb 1..6 oder eine fehlende Upload-ID ab", async () => {
    const env = neuerEnv();
    await worker.fetch(start("aufnahme.wav"), env, ctx);
    expect((await worker.fetch(teil("aufnahme.wav", 0, "x", "a"), env, ctx)).status).toBe(400);
    expect((await worker.fetch(teil("aufnahme.wav", 7, "x", "a"), env, ctx)).status).toBe(400);
    const ohneUpload = new Request("https://nestor.test/intern/spende/abc12345/aufnahme.wav?teil=1", {
      method: "PUT", body: "a", headers: { "X-Nestor-Geheimnis": "worker-geheim", "Content-Length": "1" },
    });
    expect((await worker.fetch(ohneUpload, env, ctx)).status).toBe(400);
    expect(abgelegt).toHaveLength(0);
  });

  it("ein einzelner Teil über der Teil-Obergrenze (50 MB) wird abgewiesen", async () => {
    const env = neuerEnv();
    const startAntwort = await worker.fetch(start("aufnahme.wav"), env, ctx);
    const { uploadId } = (await startAntwort.json()) as { uploadId: string };
    const zuGross = teil("aufnahme.wav", 1, uploadId, "a", { "Content-Length": String(51 * 1024 * 1024) });
    expect((await worker.fetch(zuGross, env, ctx)).status).toBe(413);
  });

  it("ein Abschluss ohne Teile oder ohne Upload-ID wird abgewiesen", async () => {
    const env = neuerEnv();
    expect((await worker.fetch(fertig("aufnahme.wav", { uploadId: "x", teile: [] }), env, ctx)).status).toBe(400);
    expect((await worker.fetch(fertig("aufnahme.wav", { teile: [{ partNumber: 1, etag: "e" }] }), env, ctx)).status).toBe(400);
  });

  it("nur die vorgesehene Methode ist je Unterbefehl erlaubt", async () => {
    const env = neuerEnv();
    const falscheMethodeStart = new Request(start("aufnahme.wav"), { method: "PUT" });
    expect((await worker.fetch(falscheMethodeStart, env, ctx)).status).toBe(405);
    const falscheMethodeFertig = new Request(fertig("aufnahme.wav", {}), { method: "PUT" });
    expect((await worker.fetch(falscheMethodeFertig, env, ctx)).status).toBe(405);
  });
});

describe("POST /intern/spende/<name>/abschluss", () => {
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
