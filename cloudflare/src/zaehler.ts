/**
 * KundenZaehler: ein Durable Object je Kunde, zählt dessen gleichzeitig laufende Meetings gegen
 * `max_meetings` (Secret KUNDEN). Durchsetzung "mit vertretbarem Aufwand" (Ticket #5) – bewusst einfach:
 *
 * - Ein Meeting zählt, sobald der Worker es zum ersten Mal sieht (keine `nestor_meeting`-Kopplung).
 * - Es zählt weiter, bis es `VERFALL_MS` lang keine Anfrage mehr hatte (Herzschlag über `/pruefen`).
 *
 * Das ist eine Näherung, kein exaktes "Meeting beendet": Der Worker erfährt vom echten Ende eines Meetings
 * nicht (das Abschluss-Ticket #3 existiert in diesem Stand noch nicht und hat keinen Rückruf zum Worker).
 * Ein beendetes, aber gerade verlassenes Meeting zählt darum bis zu `VERFALL_MS` nach, und ein Kunde kann
 * knapp an seinem Limit vorbeirutschen. Für v1 reicht das; ein echtes Ende-Signal (z. B. derselbe
 * `/intern/`-Mechanismus wie die Datenspende) ist eine naheliegende Erweiterung für Ticket #3.
 *
 * Die eigentliche Zähl-Logik steht in `zaehler-logik.ts` (ohne Workers-Laufzeit, testbar mit `npm test`);
 * hier nur die dünne Durable-Object-Hülle darum.
 */

import { DurableObject } from "cloudflare:workers";
import { pruefenUndAktualisieren, type Zustand } from "./zaehler-logik";

export { VERFALL_MS, pruefenUndAktualisieren, type Zustand } from "./zaehler-logik";

export class KundenZaehler extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/pruefen") {
      return new Response("Nur POST /pruefen.", { status: 404 });
    }
    const { meetingId, maxMeetings } = (await request.json()) as { meetingId: string; maxMeetings: number };
    const zustand = ((await this.ctx.storage.get<Zustand>("zustand")) ?? {}) as Zustand;
    const ergebnis = pruefenUndAktualisieren(zustand, meetingId, maxMeetings, Date.now());
    await this.ctx.storage.put("zustand", ergebnis.zustand);
    return Response.json({ erlaubt: ergebnis.erlaubt, aktive: ergebnis.aktive });
  }
}
