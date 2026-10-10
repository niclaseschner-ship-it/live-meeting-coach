import { describe, expect, it } from "vitest";
import { cookieLesen, cookiePruefen, cookieSigniere } from "./anmeldung";

describe("Cookie-Signatur", () => {
  it("signiert und prüft denselben Wert erfolgreich", async () => {
    const cookie = await cookieSigniere("acme", "cookie-geheimnis");
    expect(await cookiePruefen(cookie, "cookie-geheimnis")).toBe("acme");
  });

  it("verwirft ein Cookie mit falschem Geheimnis", async () => {
    const cookie = await cookieSigniere("acme", "cookie-geheimnis");
    expect(await cookiePruefen(cookie, "anderes-geheimnis")).toBeNull();
  });

  it("verwirft ein manipuliertes Cookie (anderer Kundenname, alte Signatur)", async () => {
    const cookie = await cookieSigniere("acme", "cookie-geheimnis");
    const [, signatur] = [cookie.slice(0, cookie.lastIndexOf(".")), cookie.slice(cookie.lastIndexOf(".") + 1)];
    const manipuliert = `boeser-kunde.${signatur}`;
    expect(await cookiePruefen(manipuliert, "cookie-geheimnis")).toBeNull();
  });

  it("verwirft leere oder kaputte Cookies", async () => {
    expect(await cookiePruefen(null, "x")).toBeNull();
    expect(await cookiePruefen("ohne-punkt", "x")).toBeNull();
    expect(await cookiePruefen("", "x")).toBeNull();
  });
});

describe("Cookie-Kopfzeile lesen", () => {
  it("findet den richtigen Wert unter mehreren Cookies", () => {
    expect(cookieLesen("a=1; nestor_kunde=acme.xyz; b=2", "nestor_kunde")).toBe("acme.xyz");
  });

  it("liefert null ohne passenden Namen oder ohne Kopfzeile", () => {
    expect(cookieLesen("a=1", "nestor_kunde")).toBeNull();
    expect(cookieLesen(null, "nestor_kunde")).toBeNull();
  });
});
