/**
 * KundenZaehler: ein Durable Object je Kunde, zählt dessen gleichzeitig laufende Meetings gegen
 * `max_meetings` (Secret KUNDEN). Durchsetzung "mit vertretbarem Aufwand" (Ticket #5) – bewusst einfach:
 *
 * - Ein Meeting zählt erst, wenn es wirklich gestartet wurde: `/pruefen`, aufgerufen von `/intern/meeting-start`
 *   in `index.ts`, das wiederum der Coach beim echten `/api/start` aufruft (Ticket #12) – nicht mehr schon beim
 *   bloßen Ansehen der Startseite.
 * - Es zählt weiter, bis entweder `/beenden` kommt (aktives Ende, `/intern/meeting-ende`, vom Coach bei
 *   `/api/abschluss/fertig` ausgelöst) oder `VERFALL_MS` lang keine Anfrage mehr für dieses Meeting kam.
 *
 * `VERFALL_MS` ist die Rückfalllösung für den Fall, dass der Coach sein Ende nie meldet (Browser zu, Absturz,
 * Netz weg) – seit Ticket #12 kein exaktes "Meeting beendet" mehr nötig, weil der häufige Fall (reguläres
 * Ende über "Fertig") jetzt sofort über `/beenden` freigegeben wird; nur der Rest läuft weiter über die
 * (jetzt kürzere) Verfallszeit ab.
 *
 * Die eigentliche Zähl-Logik steht in `zaehler-logik.ts` (ohne Workers-Laufzeit, testbar mit `npm test`);
 * hier nur die dünne Durable-Object-Hülle darum.
 */

import { DurableObject } from "cloudflare:workers";
import { beenden, pruefenUndAktualisieren, type Zustand } from "./zaehler-logik";

export { VERFALL_MS, beenden, pruefenUndAktualisieren, type Zustand } from "./zaehler-logik";

export class KundenZaehler extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method !== "POST") {
      return new Response("Nur POST /pruefen oder /beenden.", { status: 404 });
    }
    const zustand = ((await this.ctx.storage.get<Zustand>("zustand")) ?? {}) as Zustand;

    if (url.pathname === "/pruefen") {
      const { meetingId, maxMeetings } = (await request.json()) as { meetingId: string; maxMeetings: number };
      const ergebnis = pruefenUndAktualisieren(zustand, meetingId, maxMeetings, Date.now());
      await this.ctx.storage.put("zustand", ergebnis.zustand);
      return Response.json({ erlaubt: ergebnis.erlaubt, aktive: ergebnis.aktive });
    }
    if (url.pathname === "/beenden") {
      const { meetingId } = (await request.json()) as { meetingId: string };
      const ergebnis = beenden(zustand, meetingId, Date.now());
      await this.ctx.storage.put("zustand", ergebnis.zustand);
      return Response.json({ aktive: ergebnis.aktive });
    }
    return new Response("Nur POST /pruefen oder /beenden.", { status: 404 });
  }
}
