import { describe, expect, it } from "vitest";
import { pruefenUndAktualisieren, VERFALL_MS, type Zustand } from "./zaehler-logik";

describe("max_meetings je Kunde", () => {
  it("lässt neue Meetings bis zum Limit zu und sperrt danach", () => {
    let zustand: Zustand = {};
    const jetzt = 1_000_000;
    let r = pruefenUndAktualisieren(zustand, "m1", 2, jetzt);
    expect(r.erlaubt).toBe(true);
    zustand = r.zustand;
    r = pruefenUndAktualisieren(zustand, "m2", 2, jetzt);
    expect(r.erlaubt).toBe(true);
    zustand = r.zustand;
    r = pruefenUndAktualisieren(zustand, "m3", 2, jetzt); // drittes Meeting, Limit 2 erreicht
    expect(r.erlaubt).toBe(false);
    expect(r.aktive).toBe(2);
  });

  it("ein schon bekanntes Meeting zählt nicht doppelt gegen das Limit", () => {
    let zustand: Zustand = {};
    const jetzt = 1_000_000;
    zustand = pruefenUndAktualisieren(zustand, "m1", 1, jetzt).zustand;
    const r = pruefenUndAktualisieren(zustand, "m1", 1, jetzt + 1000); // dieselbe Meeting-ID, nur ein Herzschlag
    expect(r.erlaubt).toBe(true);
    expect(r.aktive).toBe(1);
  });

  it("ein Meeting ohne Anfrage länger als die Verfallszeit zählt nicht mehr mit", () => {
    let zustand: Zustand = {};
    const start = 1_000_000;
    zustand = pruefenUndAktualisieren(zustand, "m1", 1, start).zustand;
    const r = pruefenUndAktualisieren(zustand, "m2", 1, start + VERFALL_MS + 1000);
    expect(r.erlaubt).toBe(true); // m1 ist verfallen, Platz für m2
    expect(r.aktive).toBe(1);
  });
});
