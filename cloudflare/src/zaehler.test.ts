import { describe, expect, it } from "vitest";
import {
  beenden, pruefenUndAktualisieren, tagesdeckelErreicht, tageskostenBuchen, TAGESDECKEL_USD, VERFALL_MS,
  type Tageskosten, type Zustand,
} from "./zaehler-logik";

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

  it("die Verfallszeit ist 30 min, nicht mehr 6 h (Ticket #12)", () => {
    expect(VERFALL_MS).toBe(30 * 60 * 1000);
  });
});

describe("aktives Ende (Ticket #12, /beenden)", () => {
  it("gibt den Platz sofort frei, auch lange vor Ablauf der Verfallszeit", () => {
    let zustand: Zustand = {};
    const start = 1_000_000;
    zustand = pruefenUndAktualisieren(zustand, "m1", 1, start).zustand;
    let r = pruefenUndAktualisieren(zustand, "m2", 1, start + 1000); // Limit 1 erreicht, m2 abgewiesen
    expect(r.erlaubt).toBe(false);

    const beendet = beenden(zustand, "m1", start + 2000); // m1 aktiv beendet, weit innerhalb der Verfallszeit
    expect(beendet.aktive).toBe(0);
    r = pruefenUndAktualisieren(beendet.zustand, "m2", 1, start + 3000); // jetzt ist Platz für m2
    expect(r.erlaubt).toBe(true);
    expect(r.aktive).toBe(1);
  });

  it("ist idempotent: ein unbekanntes oder schon beendetes Meeting ist kein Fehler", () => {
    let zustand: Zustand = {};
    const jetzt = 1_000_000;
    zustand = pruefenUndAktualisieren(zustand, "m1", 1, jetzt).zustand;
    zustand = beenden(zustand, "m1", jetzt + 1000).zustand;
    const r = beenden(zustand, "m1", jetzt + 2000); // schon beendet
    expect(r.aktive).toBe(0);
    const r2 = beenden(zustand, "nie-gesehen", jetzt + 2000); // nie registriert
    expect(r2.aktive).toBe(0);
  });

  it("räumt beim Beenden nebenbei auch andere, längst verfallene Meetings auf", () => {
    let zustand: Zustand = {};
    const start = 1_000_000;
    zustand = pruefenUndAktualisieren(zustand, "alt", 5, start).zustand;
    zustand = pruefenUndAktualisieren(zustand, "neu", 5, start + VERFALL_MS + 1000).zustand;
    const r = beenden(zustand, "neu", start + VERFALL_MS + 1000);
    expect(r.aktive).toBe(0); // "alt" war schon verfallen, "neu" wurde gerade aktiv beendet
  });
});

describe("Tagesdeckel je Kunde und Tag (Ticket #64, Entscheidung Niclas 10.10.2026)", () => {
  it("liegt bei 15 $", () => {
    expect(TAGESDECKEL_USD).toBe(15);
  });

  it("ist ohne gebuchte Kosten offen", () => {
    expect(tagesdeckelErreicht(undefined, 1_000_000)).toBe(false);
  });

  it("ist erreicht, sobald die gebuchten Kosten den Deckel erreichen oder überschreiten", () => {
    let stand: Tageskosten | undefined = tageskostenBuchen(undefined, 10, 1_000_000);
    expect(tagesdeckelErreicht(stand, 1_000_000)).toBe(false);
    stand = tageskostenBuchen(stand, 5, 1_000_000);
    expect(stand.usd).toBeCloseTo(15);
    expect(tagesdeckelErreicht(stand, 1_000_000)).toBe(true);
  });

  it("fängt an einem neuen UTC-Tag wieder bei 0 $ an", () => {
    const stand = tageskostenBuchen(undefined, 15, Date.UTC(2026, 9, 10, 23, 0));
    expect(tagesdeckelErreicht(stand, Date.UTC(2026, 9, 10, 23, 30))).toBe(true); // noch derselbe UTC-Tag
    expect(tagesdeckelErreicht(stand, Date.UTC(2026, 9, 11, 0, 30))).toBe(false); // neuer UTC-Tag
  });

  it("bucht mehrere Meetings desselben Tages auf denselben Stand", () => {
    let stand: Tageskosten | undefined = tageskostenBuchen(undefined, 4, 1_000_000);
    stand = tageskostenBuchen(stand, 6, 1_000_000 + 1000);
    stand = tageskostenBuchen(stand, 2, 1_000_000 + 2000);
    expect(stand.usd).toBeCloseTo(12);
  });
});
