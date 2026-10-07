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
