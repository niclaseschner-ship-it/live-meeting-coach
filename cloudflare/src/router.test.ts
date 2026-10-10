// Worker-Router (Ticket #61, Stufe A): genau der Pfad des QR-Fehlers „Kein Meeting zugeordnet“ – Meeting-Zuordnung
// über das signierte Kopplungstoken aus dem QR-Code (#63), Meeting- und Kopplungs-Cookie ohne Login,
// Weiterleitung an den richtigen Container. Der Container ist ein Stub, der die empfangenen Kopfzeilen spiegelt.
import { afterEach, describe, expect, it, vi } from "vitest";

const aufrufe: { meetingId: string; url: string; kopf: Record<string, string> }[] = [];

vi.mock("cloudflare:workers", () => ({ DurableObject: class {} }));
vi.mock("@cloudflare/containers", () => ({
  Container: class {},
  getContainer: (_ns: unknown, meetingId: string) => ({
    fetch: async (r: Request) => {
      const kopf: Record<string, string> = {};
      r.headers.forEach((v, k) => { kopf[k] = v; });
      aufrufe.push({ meetingId, url: r.url, kopf });
      return Response.json({ meetingId, kopf });
    },
  }),
}));

const { default: worker, lokalerCoach } = await import("./index");
const { signiereMitAblauf } = await import("./anmeldung");
const { kopplungstokenSigniere, meetingCookieSigniere } = await import("./meeting");

const GEHEIM = "cookie-geheim";
const env = {
  WORKER_GEHEIMNIS: "worker-geheim",
  COOKIE_GEHEIMNIS: GEHEIM,
  KUNDEN: "{}",
  SPENDEN: { get: async () => null, put: async () => undefined, list: async () => ({ objects: [] }) },
} as unknown as Parameters<typeof worker.fetch>[1];
const ctx = { waitUntil: () => {}, passThroughOnException: () => {} } as unknown as ExecutionContext;

const anfrage = (pfad: string, kopf: Record<string, string> = {}) =>
  new Request(`https://nestor.test${pfad}`, { headers: kopf });
const token = () => kopplungstokenSigniere({ meetingId: "M1", kunde: "pilot" }, GEHEIM);
const meetingCookie = async () => encodeURIComponent(await meetingCookieSigniere({ meetingId: "M1", kunde: "pilot" }, GEHEIM));

afterEach(() => { aufrufe.length = 0; vi.unstubAllGlobals(); });

describe("QR-Kopplung ohne Login", () => {
  it("/handy?k=…&meeting=<Token> geht ohne Login an Container M1 und setzt ein signiertes Meeting-Cookie", async () => {
    const antwort = await worker.fetch(anfrage(`/handy?k=ABCDEFGH&meeting=${encodeURIComponent(await token())}`), env, ctx);
    expect(antwort.status).toBe(200);
    expect(aufrufe).toHaveLength(1);
    expect(aufrufe[0].meetingId).toBe("M1");
    expect(aufrufe[0].kopf["x-nestor-meeting"]).toBe("M1");
    expect(aufrufe[0].kopf["x-nestor-geheimnis"]).toBe("worker-geheim");
    expect(aufrufe[0].kopf["x-nestor-kunde"]).toBeUndefined();
    const keks = antwort.headers.get("Set-Cookie") ?? "";
    expect(keks).toMatch(/nestor_meeting=/);
    expect(keks).not.toMatch(/nestor_meeting=M1;/); // nie die nackte ID
    expect(await antwort.text()).not.toContain("Kein Meeting zugeordnet");
  });

  it("die nackte Meeting-ID im QR wird nicht mehr akzeptiert (kein Container)", async () => {
    const antwort = await worker.fetch(anfrage("/handy?k=ABCDEFGH&meeting=M1"), env, ctx);
    expect(antwort.status).toBe(400);
    expect(aufrufe).toHaveLength(0);
  });

  it("Folgeanfrage mit Kopplungs- und signiertem Meeting-Cookie erreicht denselben Container (kein 400, kein Login)", async () => {
    const antwort = await worker.fetch(
      anfrage("/api/zustand", { Cookie: `lmc_kopplung=ABCDEFGH; nestor_meeting=${await meetingCookie()}` }), env, ctx);
    expect(antwort.status).toBe(200);
    expect(aufrufe[0].meetingId).toBe("M1");
  });

  it("/handy nach dem 303 des Coachs (ohne Query) bleibt über das Meeting-Cookie gekoppelt", async () => {
    const antwort = await worker.fetch(anfrage("/handy", { Cookie: `nestor_meeting=${await meetingCookie()}` }), env, ctx);
    expect(antwort.status).toBe(200);
    expect(aufrufe[0].meetingId).toBe("M1");
  });

  it("ohne Cookie, ohne Login und ohne Token gibt es 400 „Kein Meeting zugeordnet“ – kein Container", async () => {
    const antwort = await worker.fetch(anfrage("/handy"), env, ctx);
    expect(antwort.status).toBe(400);
    expect(await antwort.text()).toContain("Kein Meeting zugeordnet");
    expect(aufrufe).toHaveLength(0);
  });

  it("Dashboard ohne Login leitet auf /anmelden um", async () => {
    const antwort = await worker.fetch(anfrage("/meeting"), env, ctx);
    expect(antwort.status).toBe(303);
    expect(antwort.headers.get("Location")).toMatch(/\/anmelden$/);
    expect(aufrufe).toHaveLength(0);
  });

  it("vom Browser gesetzte Vertrauenskopfzeilen werden nicht durchgereicht", async () => {
    await worker.fetch(anfrage(`/handy?meeting=${encodeURIComponent(await token())}`, {
      "X-Nestor-Kunde": "eingeschmuggelt", "X-Nestor-Geheimnis": "falsch" }), env, ctx);
    expect(aufrufe[0].kopf["x-nestor-kunde"]).toBeUndefined();
    expect(aufrufe[0].kopf["x-nestor-geheimnis"]).toBe("worker-geheim");
  });
});

describe("Angemeldet", () => {
  it("ohne Meeting-Cookie bekommt der Kunde ein neues Meeting und dessen Cookie", async () => {
    const kunde = await signiereMitAblauf("kunde", "pilot", GEHEIM, Date.now(), 3600_000);
    const antwort = await worker.fetch(anfrage("/meeting", { Cookie: `nestor_kunde=${encodeURIComponent(kunde)}` }),
      env, ctx);
    expect(antwort.status).toBe(200);
    expect(aufrufe[0].meetingId).toMatch(/^[0-9a-f-]{36}$/);
    expect(aufrufe[0].kopf["x-nestor-kunde"]).toBe("pilot");
    expect(antwort.headers.get("Set-Cookie") ?? "").toMatch(/nestor_meeting=/);
  });
});

describe("Testnaht LOKAL_COACH_URL (nur wrangler dev der Pipeline)", () => {
  it("ist ohne Variable aus – dann bleibt es beim Container", () => {
    expect(lokalerCoach({})).toBeNull();
  });

  it("reicht Pfad, Query und Kopfzeilen an den lokalen Coach weiter und nennt den Ursprungshost", async () => {
    const gesehen: Request[] = [];
    vi.stubGlobal("fetch", async (r: Request) => { gesehen.push(r); return new Response("ok"); });
    const t = encodeURIComponent(await token());
    const antwort = await worker.fetch(anfrage(`/handy?k=ABCDEFGH&meeting=${t}`),
      { ...env, LOKAL_COACH_URL: "http://127.0.0.1:18000" } as typeof env, ctx);
    expect(antwort.status).toBe(200);
    expect(aufrufe).toHaveLength(0); // kein Container
    expect(gesehen[0].url).toBe(`http://127.0.0.1:18000/handy?k=ABCDEFGH&meeting=${t}`);
    expect(gesehen[0].headers.get("X-Forwarded-Host")).toBe("nestor.test");
    expect(gesehen[0].headers.get("X-Nestor-Meeting")).toBe("M1");
    expect(antwort.headers.get("Set-Cookie") ?? "").toMatch(/nestor_meeting=/);
  });
});
