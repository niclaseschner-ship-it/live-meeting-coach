/**
 * Reine Zähl-Logik für `KundenZaehler` (`zaehler.ts`), ohne jeden Import aus `cloudflare:workers` – nur so
 * lässt sie sich mit `npm test` (vitest, plain Node) prüfen, ohne die Workers-Laufzeit (Miniflare) zu
 * brauchen. Siehe `zaehler.ts` für die Begründung der Näherung (Verfallszeit statt echtem Ende-Signal).
 */

export const VERFALL_MS = 6 * 60 * 60 * 1000; // 6 h ohne Anfrage = Meeting gilt als vorbei

export interface Zustand {
  [meetingId: string]: number; // zuletzt gesehen (Date.now())
}

export function pruefenUndAktualisieren(
  zustand: Zustand,
  meetingId: string,
  maxMeetings: number,
  jetzt: number,
): { erlaubt: boolean; zustand: Zustand; aktive: number } {
  const bereinigt: Zustand = {};
  for (const [id, letzt] of Object.entries(zustand)) {
    if (jetzt - letzt <= VERFALL_MS) bereinigt[id] = letzt;
  }
  const bekannt = meetingId in bereinigt;
  if (!bekannt && Object.keys(bereinigt).length >= maxMeetings) {
    return { erlaubt: false, zustand: bereinigt, aktive: Object.keys(bereinigt).length };
  }
  bereinigt[meetingId] = jetzt;
  return { erlaubt: true, zustand: bereinigt, aktive: Object.keys(bereinigt).length };
}
