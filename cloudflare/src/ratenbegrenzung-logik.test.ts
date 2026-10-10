import { describe, expect, it } from "vitest";
import { pruefenUndErhoehen, type Zustand } from "./ratenbegrenzung-logik";

describe("IP-Ratenbegrenzung", () => {
  it("lässt Versuche bis zum Limit zu und sperrt danach, innerhalb des Fensters", () => {
    let zustand: Zustand = {};
    const jetzt = 1_000_000;
    const grenze = { limit: 2, fensterMs: 60_000 };
    let r = pruefenUndErhoehen(zustand, "anmelden", jetzt, grenze);
    expect(r.erlaubt).toBe(true);
    zustand = r.zustand;
    r = pruefenUndErhoehen(zustand, "anmelden", jetzt + 1000, grenze);
    expect(r.erlaubt).toBe(true);
    zustand = r.zustand;
    r = pruefenUndErhoehen(zustand, "anmelden", jetzt + 2000, grenze); // dritter Versuch, Limit 2 erreicht
    expect(r.erlaubt).toBe(false);
  });

  it("verschiedene Zwecke zählen getrennt", () => {
    let zustand: Zustand = {};
    const jetzt = 1_000_000;
    const grenze = { limit: 1, fensterMs: 60_000 };
    zustand = pruefenUndErhoehen(zustand, "anmelden", jetzt, grenze).zustand;
    expect(pruefenUndErhoehen(zustand, "anmelden", jetzt + 1, grenze).erlaubt).toBe(false);
    expect(pruefenUndErhoehen(zustand, "pin", jetzt + 1, grenze).erlaubt).toBe(true); // eigener Zweck, eigenes Kontingent
  });

  it("alte Versuche außerhalb des Fensters zählen nicht mehr mit", () => {
    let zustand: Zustand = {};
    const start = 1_000_000;
    const grenze = { limit: 1, fensterMs: 60_000 };
    zustand = pruefenUndErhoehen(zustand, "anmelden", start, grenze).zustand;
    const r = pruefenUndErhoehen(zustand, "anmelden", start + 60_001, grenze); // Fenster abgelaufen
    expect(r.erlaubt).toBe(true);
  });
});
