import { describe, expect, it } from "vitest";
import { normalisiereAnmeldung, pinHash, pinSeite, registrierungsSeite } from "./pilotzugang";

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
