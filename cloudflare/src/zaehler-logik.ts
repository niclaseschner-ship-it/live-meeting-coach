/**
 * Reine Zähl-Logik für `KundenZaehler` (`zaehler.ts`), ohne jeden Import aus `cloudflare:workers` – nur so
 * lässt sie sich mit `npm test` (vitest, plain Node) prüfen, ohne die Workers-Laufzeit (Miniflare) zu
 * brauchen. Siehe `zaehler.ts` für die Begründung der Näherung (Verfallszeit statt echtem Ende-Signal).
 *
 * Ticket #12: Ein Meeting zählt erst, wenn es gestartet wurde (`pruefenUndAktualisieren`, aufgerufen von
 * `/intern/meeting-start` in `index.ts`, ausgelöst durch `coach/server.py` `/api/start`) – nicht mehr schon
 * beim bloßen Ansehen der Startseite. Aktiv beendete Meetings (`/api/abschluss/fertig` → `/intern/meeting-ende`)
 * geben ihren Platz sofort über `beenden()` frei, statt auf die (jetzt kürzere) Verfallszeit zu warten.
 */

export const VERFALL_MS = 30 * 60 * 1000; // 30 min ohne Anfrage = Meeting gilt als vorbei (vorher 6 h, Ticket #12)

export interface Zustand {
  [meetingId: string]: number; // zuletzt gesehen (Date.now())
}

function ohneAbgelaufene(zustand: Zustand, jetzt: number): Zustand {
  const bereinigt: Zustand = {};
  for (const [id, letzt] of Object.entries(zustand)) {
    if (jetzt - letzt <= VERFALL_MS) bereinigt[id] = letzt;
  }
  return bereinigt;
}

export function pruefenUndAktualisieren(
  zustand: Zustand,
  meetingId: string,
  maxMeetings: number,
  jetzt: number,
): { erlaubt: boolean; zustand: Zustand; aktive: number } {
  const bereinigt = ohneAbgelaufene(zustand, jetzt);
  const bekannt = meetingId in bereinigt;
  if (!bekannt && Object.keys(bereinigt).length >= maxMeetings) {
    return { erlaubt: false, zustand: bereinigt, aktive: Object.keys(bereinigt).length };
  }
  bereinigt[meetingId] = jetzt;
  return { erlaubt: true, zustand: bereinigt, aktive: Object.keys(bereinigt).length };
}

/** Gibt den Platz eines beendeten Meetings sofort frei (Ticket #12, `/intern/meeting-ende`) – unabhängig davon,
 * ob seine Verfallszeit schon erreicht ist. Kein bekanntes Meeting unter dieser ID ist kein Fehler (idempotent). */
export function beenden(zustand: Zustand, meetingId: string, jetzt: number): { zustand: Zustand; aktive: number } {
  const bereinigt = ohneAbgelaufene(zustand, jetzt);
  delete bereinigt[meetingId];
  return { zustand: bereinigt, aktive: Object.keys(bereinigt).length };
}

/**
 * Tagesdeckel je Kunde (Ticket #64, Entscheidung Niclas 10.10.2026): 15 $ Kosten je Kunde und Tag. Der Tag ist
 * der UTC-Kalendertag – einfach und robust gegen Zeitzonen; ein Tageswechsel, der ein paar Stunden neben der
 * realen Mitternacht liegt, ist für einen Kostendeckel unkritisch.
 *
 * Gebucht wird beim Meeting-Ende (`/intern/meeting-ende` in index.ts, `coach/api_abschluss.py` liefert
 * `kostenUsd` mit); geprüft beim Start (`/intern/meeting-start`, neben `pruefenUndAktualisieren` oben).
 */
export const TAGESDECKEL_USD = 15;

export interface Tageskosten {
  tag: string; // YYYY-MM-DD, UTC
  usd: number;
}

function tagUtc(jetzt: number): string {
  return new Date(jetzt).toISOString().slice(0, 10);
}

/** Heutiger Stand: ein neuer UTC-Tag fängt wieder bei 0 $ an. */
function heutigerStand(stand: Tageskosten | undefined, jetzt: number): Tageskosten {
  const tag = tagUtc(jetzt);
  return stand && stand.tag === tag ? stand : { tag, usd: 0 };
}

export function tagesdeckelErreicht(stand: Tageskosten | undefined, jetzt: number, deckel = TAGESDECKEL_USD): boolean {
  return heutigerStand(stand, jetzt).usd >= deckel;
}

export function tageskostenBuchen(stand: Tageskosten | undefined, usd: number, jetzt: number): Tageskosten {
  const heute = heutigerStand(stand, jetzt);
  return { tag: heute.tag, usd: heute.usd + usd };
}
