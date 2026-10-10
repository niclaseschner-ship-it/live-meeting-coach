import { describe, expect, it } from "vitest";
import { sha256Hex } from "./anmeldung";
import {
  type Interessent, kundeAktiv, normalisiereAnmeldung, type PilotEnv, pinHash, pinSeite, registrierungsSeite,
  statusCacheErzeugen, testzugangErlaubt, testzugangMailPasst, testzugangPinPruefen,
} from "./pilotzugang";

describe("Pilot-Registrierung", () => {
  it("verlangt Name, gültige Mail und Herkunft", () => {
    const f = new FormData();
    f.set("name", "  Ada   Beispiel ");
    f.set("email", "ADA@EXAMPLE.DE ");
    f.set("herkunft", " über   die Workshop-Gruppe ");
    f.set("datenschutz", "ja");
    expect(normalisiereAnmeldung(f)).toEqual({
      name: "Ada Beispiel", email: "ada@example.de", herkunft: "über die Workshop-Gruppe",
    });
    f.set("herkunft", "");
    expect(normalisiereAnmeldung(f)).toBeNull();
  });

  it("bindet einen PIN-Hash an Mailadresse und Geheimnis", async () => {
    expect(await pinHash("a@example.de", "123456", "g")).not.toBe(await pinHash("b@example.de", "123456", "g"));
  });

  it("maskiert Nutzereingaben in den Seiten", () => {
    expect(registrierungsSeite("<b>kaputt</b>")).toContain("&lt;b&gt;kaputt&lt;/b&gt;");
    expect(pinSeite('a\"@example.de')).not.toContain('value="a\"@example.de"');
  });
});

function envMit(datensatz: Interessent | null): PilotEnv {
  return {
    SPENDEN: { get: async () => (datensatz ? { json: async () => datensatz } : null) } as unknown as R2Bucket,
    PIN_GEHEIMNIS: "g", GMAIL_SMTP_PASSWORT: "x", MAIL_VON: "nestor@example.de",
  };
}

const INTERESSENT_BASIS: Interessent = {
  name: "Ada", email: "ada@example.de", herkunft: "Workshop", erstellt_at: 0, letzter_pin_at: 0,
  pin_hash: "", pin_bis: 0, pin_versuche: 0, status: "aktiv",
};

describe("Testzugang (Ticket #75): Mail + fester PIN, nur Dev/Staging", () => {
  const mail = "e2e@nestor.lokal";
  const env = async () => ({ TESTZUGANG: JSON.stringify({ mail, pinHash: await sha256Hex("123456") }) });

  it("passt bei richtiger Mail und WORKER_NAME ungleich 'nestor'", async () => {
    const e = { ...(await env()), WORKER_NAME: "nestor-staging" };
    expect(testzugangMailPasst(e, mail)).toBe(true);
    expect(await testzugangPinPruefen(e, mail, "123456")).toBe("ok");
    expect(await testzugangPinPruefen(e, mail, "000000")).toBe("falsch");
  });

  it("ist für jede andere Mail nicht zuständig (null, normaler Fluss prüft weiter)", async () => {
    const e = { ...(await env()), WORKER_NAME: "nestor-staging" };
    expect(await testzugangPinPruefen(e, "jemand@anderes.de", "123456")).toBeNull();
  });

  it("ist ohne WORKER_NAME gesperrt (im Zweifel geschlossen)", () => {
    expect(testzugangErlaubt(undefined)).toBe(false);
    expect(testzugangErlaubt("")).toBe(false);
  });

  it("wird in prod (WORKER_NAME 'nestor') hart ignoriert, selbst wenn das Secret gesetzt ist", async () => {
    const e = { ...(await env()), WORKER_NAME: "nestor" };
    expect(testzugangMailPasst(e, mail)).toBe(false);
    expect(await testzugangPinPruefen(e, mail, "123456")).toBeNull();
  });

  it("ist ohne gesetztes Secret nie zuständig", async () => {
    expect(await testzugangPinPruefen({ WORKER_NAME: "nestor-staging" }, mail, "123456")).toBeNull();
  });
});

describe("Status-Cache (gesperrt/wartet wirkt sofort, Ticket #63)", () => {
  it("ist aktiv ohne Interessenten-Datensatz (Legacy-Passwortkunde)", async () => {
    expect(await kundeAktiv(envMit(null), "acme", statusCacheErzeugen())).toBe(true);
  });

  it("ist aktiv bei Status 'aktiv', gesperrt bei 'gesperrt' oder 'wartet'", async () => {
    expect(await kundeAktiv(envMit({ ...INTERESSENT_BASIS, status: "aktiv" }), "ada@example.de", statusCacheErzeugen())).toBe(true);
    expect(await kundeAktiv(envMit({ ...INTERESSENT_BASIS, status: "gesperrt" }), "ada@example.de", statusCacheErzeugen())).toBe(false);
    expect(await kundeAktiv(envMit({ ...INTERESSENT_BASIS, status: "wartet" }), "ada@example.de", statusCacheErzeugen())).toBe(false);
  });

  it("hält den Testzugang trotz Altdatensatz 'wartet' aktiv, in prod nicht", async () => {
    const test = { TESTZUGANG: JSON.stringify({ mail: "ada@example.de", pinHash: "x" }) };
    const wartet = envMit({ ...INTERESSENT_BASIS, status: "wartet" });
    expect(await kundeAktiv({ ...wartet, ...test, WORKER_NAME: "nestor-staging" }, "ada@example.de", statusCacheErzeugen())).toBe(true);
    expect(await kundeAktiv({ ...wartet, ...test, WORKER_NAME: "nestor" }, "ada@example.de", statusCacheErzeugen())).toBe(false);
  });

  it("liest innerhalb von 5 Minuten aus dem Cache, nicht erneut aus R2", async () => {
    const cache = statusCacheErzeugen();
    const gelesen = { anzahl: 0 };
    const env: PilotEnv = {
      SPENDEN: {
        get: async () => { gelesen.anzahl++; return { json: async () => ({ ...INTERESSENT_BASIS, status: "aktiv" }) }; },
      } as unknown as R2Bucket,
      PIN_GEHEIMNIS: "g", GMAIL_SMTP_PASSWORT: "x", MAIL_VON: "nestor@example.de",
    };
    const jetzt = 1_000_000;
    expect(await kundeAktiv(env, "ada@example.de", cache, jetzt)).toBe(true);
    expect(await kundeAktiv(env, "ada@example.de", cache, jetzt + 60_000)).toBe(true); // aus dem Cache
    expect(gelesen.anzahl).toBe(1);
    await kundeAktiv(env, "ada@example.de", cache, jetzt + 5 * 60_000 + 1); // Cache abgelaufen
    expect(gelesen.anzahl).toBe(2);
  });
});
