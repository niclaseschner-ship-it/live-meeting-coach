import { describe, expect, it } from "vitest";
import {
  type Interessent, kundeAktiv, normalisiereAnmeldung, type PilotEnv, pinHash, pinSeite, registrierungsSeite,
  statusCacheErzeugen,
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
  pin_hash: "", pin_bis: 0, pin_versuche: 0, max_meetings: 1, status: "aktiv",
};

describe("Status-Cache (gesperrt/wartet wirkt sofort, Ticket #63)", () => {
  it("ist aktiv ohne Interessenten-Datensatz (Legacy-Passwortkunde)", async () => {
    expect(await kundeAktiv(envMit(null), "acme", statusCacheErzeugen())).toBe(true);
  });

  it("ist aktiv bei Status 'aktiv', gesperrt bei 'gesperrt' oder 'wartet'", async () => {
    expect(await kundeAktiv(envMit({ ...INTERESSENT_BASIS, status: "aktiv" }), "ada@example.de", statusCacheErzeugen())).toBe(true);
    expect(await kundeAktiv(envMit({ ...INTERESSENT_BASIS, status: "gesperrt" }), "ada@example.de", statusCacheErzeugen())).toBe(false);
    expect(await kundeAktiv(envMit({ ...INTERESSENT_BASIS, status: "wartet" }), "ada@example.de", statusCacheErzeugen())).toBe(false);
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
