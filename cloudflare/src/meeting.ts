/**
 * Signierte Meeting-Identität (Ticket #63, Befund 1 in review/r3_sicherheit.md und U1 in review/r2_architektur.md
 * Abschnitt 6.A): Meeting-IDs erzeugt nur der Worker. Weder das Cookie `nestor_meeting` noch der `?meeting=`-
 * Parameter aus dem QR-Code werden mehr als nackte ID vertraut – beide tragen eine HMAC-Signatur (wiederverwendet
 * aus `anmeldung.ts`) über Meeting-ID, Kunde und Ablaufzeit. Ohne gültige, unabgelaufene Signatur gibt es in
 * `index.ts` kein `getContainer`.
 *
 * Zwei eigene Zwecke ("meeting" fürs langlebige Cookie, "kopplung" fürs kurzlebige QR-Token) trennen die beiden
 * Verwendungen trotz gleichem Geheimnis (`COOKIE_GEHEIMNIS`) – ein Kopplungstoken lässt sich so nicht als
 * Dauer-Cookie weiterverwenden und umgekehrt. Die QR-Kopplung ohne Login am Handy bleibt dadurch unverändert
 * möglich: Das Kopplungstoken trägt den Kunden mit, der Handy braucht kein eigenes Login-Cookie.
 */

import { pruefeMitAblauf, signiereMitAblauf } from "./anmeldung";

export interface MeetingTicket {
  meetingId: string;
  kunde: string;
}

/** Wie lange das Meeting-Cookie gilt – deckungsgleich mit dem bisherigen `Max-Age` in index.ts. */
export const MEETING_COOKIE_GUELTIGKEIT_MS = 30 * 24 * 60 * 60 * 1000;

/** Das QR-Kopplungstoken ist bewusst kurzlebig: Es muss nur den einen Scan überleben, nicht tagelang gültig
 * bleiben (jeder Dashboard-Aufruf von `/api/kopplung` kann ein frisches Token holen). */
export const KOPPLUNGSTOKEN_GUELTIGKEIT_MS = 15 * 60 * 1000;

export function meetingCookieSigniere(ticket: MeetingTicket, geheimnis: string, jetzt = Date.now()): Promise<string> {
  return signiereMitAblauf("meeting", ticket, geheimnis, jetzt, MEETING_COOKIE_GUELTIGKEIT_MS);
}

export function meetingCookiePruefen(
  wert: string | null | undefined,
  geheimnis: string,
  jetzt = Date.now(),
): Promise<MeetingTicket | null> {
  return pruefeMitAblauf<MeetingTicket>("meeting", wert, geheimnis, jetzt);
}

export function kopplungstokenSigniere(ticket: MeetingTicket, geheimnis: string, jetzt = Date.now()): Promise<string> {
  return signiereMitAblauf("kopplung", ticket, geheimnis, jetzt, KOPPLUNGSTOKEN_GUELTIGKEIT_MS);
}

export function kopplungstokenPruefen(
  wert: string | null | undefined,
  geheimnis: string,
  jetzt = Date.now(),
): Promise<MeetingTicket | null> {
  return pruefeMitAblauf<MeetingTicket>("kopplung", wert, geheimnis, jetzt);
}
