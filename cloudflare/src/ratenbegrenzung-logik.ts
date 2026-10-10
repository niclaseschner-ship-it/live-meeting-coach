/**
 * Reine Zählerlogik für die IP-Ratenbegrenzung (Ticket #63): gleitendes Zeitfenster je Zweck ("anmelden"/
 * "pin"), ohne jeden Import aus `cloudflare:workers` – nur so lässt sie sich mit `npm test` (vitest, plain
 * Node) prüfen. Dünne Durable-Object-Hülle (ein Objekt je IP-Adresse) in `ratenbegrenzung.ts`.
 *
 * Ergänzt die bestehende Pro-Adresse-Sperre in `pilotzugang.ts` (60 s zwischen zwei Codes für dieselbe Mail) um
 * eine IP-weite Grenze – schützt zusätzlich gegen Mail-Flut mit wechselnden erfundenen Adressen und gegen
 * PIN-Rateversuche über viele Mailadressen hinweg von derselben Adresse aus (review/r3_sicherheit.md, Befund 2).
 */

export interface Zustand {
  [zweck: string]: number[]; // Zeitstempel (Date.now()) der Versuche in diesem Zweck, noch im Fenster
}

export interface Grenze {
  limit: number;
  fensterMs: number;
}

export function pruefenUndErhoehen(
  zustand: Zustand,
  zweck: string,
  jetzt: number,
  grenze: Grenze,
): { erlaubt: boolean; zustand: Zustand } {
  const bisherige = (zustand[zweck] ?? []).filter((t) => jetzt - t < grenze.fensterMs);
  if (bisherige.length >= grenze.limit) {
    return { erlaubt: false, zustand: { ...zustand, [zweck]: bisherige } };
  }
  return { erlaubt: true, zustand: { ...zustand, [zweck]: [...bisherige, jetzt] } };
}
